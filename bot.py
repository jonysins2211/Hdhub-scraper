#!/usr/bin/env python3
"""
Telegram Auto-Post Bot for HDhub4u Content
Admin-only bot that automatically posts content to Telegram channels
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import Database
from scraper import HDhub4uScraper
from cache_manager import CacheManager

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# Global instances
db = Database()
scraper = HDhub4uScraper()
cache = CacheManager()
scheduler = AsyncIOScheduler()
PLOT_PREVIEW_LIMIT = 200


def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    return user_id in ADMIN_IDS


async def admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Decorator function to check admin access"""
    if not is_admin(update.effective_user.id):
        message = update.effective_message
        if message:
            await message.reply_text("⛔ Access denied. This bot is for admins only.")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    if not await admin_only(update, context):
        return
    
    welcome_text = """
🤖 *HDhub4u Auto-Post Bot*

Welcome Admin! This bot automatically posts content to your Telegram channel.

*Available Commands:*
/setchannel - Set target channel
/settimer - Set auto-post interval (in minutes)
/status - View bot status
/posted - View post history
/start_autopost - Start auto-posting
/stop_autopost - Stop auto-posting
/force_post - Manually trigger a post
/stats - View statistics

*Current Status:*
Channel: {channel}
Timer: {timer} minutes
Auto-posting: {status}
"""
    
    channel = _escape_md(db.get_setting('channel') or 'Not set')
    timer = _escape_md(db.get_setting('timer') or '5')
    auto_status = '✅ Active' if db.get_setting('auto_post_enabled') == 'true' else '❌ Inactive'
    
    await update.message.reply_text(
        welcome_text.format(channel=channel, timer=timer, status=auto_status),
        parse_mode=ParseMode.MARKDOWN
    )


async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the target channel for posting"""
    if not await admin_only(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "📢 Please provide channel username or ID\n"
            "Example: `/setchannel @mychannel` or `/setchannel -1001234567890`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    channel = context.args[0]
    db.set_setting('channel', channel)
    
    await update.message.reply_text(
        f"✅ Channel set to: `{channel}`\n"
        f"Make sure the bot is an admin in this channel!",
        parse_mode=ParseMode.MARKDOWN
    )


async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set auto-post timer interval"""
    if not await admin_only(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "⏱️ Please provide interval in minutes\n"
            "Example: `/settimer 5` (for 5 minutes)",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        minutes = int(context.args[0])
        if minutes < 1:
            await update.message.reply_text("⚠️ Timer must be at least 1 minute")
            return
        
        db.set_setting('timer', str(minutes))
        
        # Reschedule if auto-posting is active
        if db.get_setting('auto_post_enabled') == 'true':
            restart_scheduler(context.application)
        
        await update.message.reply_text(
            f"✅ Auto-post interval set to: {minutes} minutes",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text("⚠️ Please provide a valid number")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    if not await admin_only(update, context):
        return
    
    channel = _escape_md(db.get_setting('channel') or 'Not set')
    timer = _escape_md(db.get_setting('timer') or '5')
    auto_status = db.get_setting('auto_post_enabled') == 'true'
    
    total_posts = db.get_total_posts()
    last_post = _escape_md(db.get_last_post_time() or 'Never')
    
    status_text = f"""
📊 *Bot Status*

*Configuration:*
• Channel: `{channel}`
• Timer: {timer} minutes
• Auto-posting: {'✅ Active' if auto_status else '❌ Inactive'}

*Statistics:*
• Total posts: {total_posts}
• Last post: {last_post}
• Cache entries: {cache.size()}

*System:*
• Database: ✅ Connected
• Scraper: ✅ Ready
"""
    
    await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)


async def posted_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent post history"""
    if not await admin_only(update, context):
        return
    
    posts = db.get_recent_posts(limit=10)
    
    if not posts:
        await update.message.reply_text("📝 No posts yet!")
        return
    
    history_text = "*Recent Posts:*\n\n"
    for post in posts:
        title = _escape_md(post['title'])
        posted_at = _escape_md(post['posted_at'])
        history_text += f"• {title}\n  _{posted_at}_\n\n"
    
    await update.message.reply_text(history_text, parse_mode=ParseMode.MARKDOWN)


async def start_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start auto-posting"""
    if not await admin_only(update, context):
        return
    
    channel = db.get_setting('channel')
    if not channel:
        await update.message.reply_text("⚠️ Please set a channel first using /setchannel")
        return
    
    db.set_setting('auto_post_enabled', 'true')
    restart_scheduler(context.application)
    
    await update.message.reply_text(
        "✅ Auto-posting started!\n"
        f"Posts will be published every {db.get_setting('timer') or '5'} minutes."
    )


async def stop_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop auto-posting"""
    if not await admin_only(update, context):
        return
    
    db.set_setting('auto_post_enabled', 'false')
    scheduler.remove_all_jobs()
    
    await update.message.reply_text("⏸️ Auto-posting stopped!")


async def force_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a post"""
    if not await admin_only(update, context):
        return
    
    channel = db.get_setting('channel')
    if not channel:
        await update.message.reply_text("⚠️ Please set a channel first using /setchannel")
        return
    
    await update.message.reply_text("🔄 Fetching content...")
    
    try:
        await post_to_channel(context.application, channel, force=True)
        await update.message.reply_text("✅ Content posted successfully!")
    except Exception as e:
        logger.error(f"Error posting: {e}")
        await update.message.reply_text(f"❌ Error posting: {str(e)}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed statistics"""
    if not await admin_only(update, context):
        return
    
    total_posts = db.get_total_posts()
    today_posts = db.get_posts_count_today()
    unique_content = db.get_unique_content_count()
    
    stats_text = f"""
📈 *Detailed Statistics*

*Posts:*
• Total: {total_posts}
• Today: {today_posts}
• Unique content: {unique_content}

*Cache:*
• Entries: {cache.size()}
• Hit rate: {cache.get_hit_rate():.1f}%

*Database:*
• Size: {db.get_size_mb():.2f} MB
"""
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)


async def post_to_channel(application: Application, channel: str, force: bool = False):
    """Main function to post content to channel"""
    try:
        # Get content from scraper with caching
        content = await scraper.get_latest_content(cache)
        
        if not content:
            logger.warning("No content available to post")
            return
        
        posted_count = 0
        
        # Check for duplicates
        for item in content:
            if db.is_posted(item['url']):
                logger.info(f"Skipping duplicate: {item['title']}")
                continue
            
            # Get download links for this item
            try:
                download_links = await scraper.get_download_links(item['url'], cache)
                item['download_links'] = download_links
            except Exception as e:
                logger.error(f"Error getting download links: {e}")
                item['download_links'] = []
            
            # Format message
            message = format_post_message(item)
            
            # Create inline keyboard with download links
            keyboard = create_download_keyboard(item)
            
            # Send to channel
            try:
                if item.get('poster_url'):
                    await application.bot.send_photo(
                        chat_id=channel,
                        photo=item['poster_url'],
                        caption=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
                else:
                    await application.bot.send_message(
                        chat_id=channel,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
                
                # Record in database
                db.add_post(item['title'], item['url'])
                logger.info(f"Posted: {item['title']}")
                
                posted_count += 1
                
                # Limit posts per run (avoid flooding)
                if posted_count >= 3:
                    logger.info("Reached post limit for this run")
                    break
                
                # Add delay between posts
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error posting {item['title']}: {e}")
                continue
        
        if posted_count == 0:
            logger.info("No new content to post (all duplicates)")
        
    except Exception as e:
        logger.error(f"Error in post_to_channel: {e}")
        raise


def _escape_md(value) -> str:
    """
    Escape text for Markdown (version 1) parse mode.
    Converts non-string input to string and returns an empty string for None.
    """
    if value is None:
        return ''
    return escape_markdown(str(value), version=1)


def format_post_message(item: dict) -> str:
    """Format content item into a post message"""
    title = _escape_md(item.get('title', 'Unknown'))
    quality = _escape_md(item.get('quality', ''))

    genre_raw = item.get('genre', [])
    if isinstance(genre_raw, (list, tuple)):
        escaped_genres = [_escape_md(g) for g in genre_raw]
        genre = ', '.join(escaped_genres)
    else:
        genre = _escape_md(genre_raw)

    year = _escape_md(item.get('year', ''))
    rating = _escape_md(item.get('rating', ''))

    plot_raw = item.get('plot', '')
    plot = ''
    if plot_raw:
        needs_ellipsis = len(plot_raw) > PLOT_PREVIEW_LIMIT
        shortened = plot_raw[:PLOT_PREVIEW_LIMIT]
        plot = _escape_md(shortened)
        if needs_ellipsis:
            plot += '...'
    download_count = len(item.get('download_links', []))
    
    message = f"🎬 *{title}*"
    
    if quality:
        message += f"\n\n📊 Quality: {quality}"
    if year:
        message += f"\n📅 Year: {year}"
    if rating:
        message += f"\n⭐ Rating: {rating}"
    if genre:
        message += f"\n🎭 Genre: {genre}"
    if plot:
        message += f"\n\n📝 {plot}"
    
    # Add download links count indicator
    if download_count > 0:
        message += f"\n\n💾 {download_count} Download {'Link' if download_count == 1 else 'Links'} Available"
        message += f"\n👇 _Click the buttons below to download_"
    
    return message


def create_download_keyboard(item: dict) -> InlineKeyboardMarkup:
    """
    Create inline keyboard with download links
    Supports multiple links with quality labels and organized layout
    """
    buttons = []
    
    links = item.get('download_links', [])
    
    # Group links by quality for better organization
    quality_map = {
        '4K': '🎥 4K UHD',
        '2160p': '🎥 4K UHD',
        '1080p': '📺 1080p FHD',
        '720p': '📱 720p HD',
        '480p': '📱 480p SD',
        'Download': '📥 Download'
    }
    
    # Add download link buttons (limit to 8 for better UX)
    for i, link in enumerate(links[:8]):
        quality = link.get('quality', f'Link {i+1}')
        
        # Use better emoji based on quality
        button_text = quality_map.get(quality, f'📥 {quality}')
        
        buttons.append([InlineKeyboardButton(button_text, url=link['url'])])
    
    # Add "More Info" button with item URL if available
    if item.get('url'):
        buttons.append([InlineKeyboardButton('ℹ️ More Info', url=item['url'])])
    
    return InlineKeyboardMarkup(buttons) if buttons else None


def restart_scheduler(application: Application):
    """Restart the scheduler with current settings"""
    scheduler.remove_all_jobs()
    
    if db.get_setting('auto_post_enabled') == 'true':
        timer = int(db.get_setting('timer') or '5')
        channel = db.get_setting('channel')
        
        if channel:
            scheduler.add_job(
                post_to_channel,
                'interval',
                minutes=timer,
                args=[application, channel],
                id='auto_post',
                replace_existing=True
            )
            logger.info(f"Scheduler started: posting every {timer} minutes")


async def post_init(application: Application):
    """Initialize bot on startup"""
    logger.info("Bot started!")
    
    # Start scheduler if auto-posting is enabled
    if db.get_setting('auto_post_enabled') == 'true':
        restart_scheduler(application)


def main():
    """Main function to run the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    if not ADMIN_IDS:
        logger.error("ADMIN_IDS not set!")
        return
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setchannel", set_channel))
    application.add_handler(CommandHandler("settimer", set_timer))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("posted", posted_history))
    application.add_handler(CommandHandler("start_autopost", start_autopost))
    application.add_handler(CommandHandler("stop_autopost", stop_autopost))
    application.add_handler(CommandHandler("force_post", force_post))
    application.add_handler(CommandHandler("stats", stats))
    
    # Start scheduler
    scheduler.start()
    
    # Run bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
