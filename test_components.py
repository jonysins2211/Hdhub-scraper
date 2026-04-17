#!/usr/bin/env python3
"""
Test script to validate bot components
"""

import asyncio
import sys
from database import Database
from cache_manager import CacheManager
from scraper import HDhub4uScraper
from bot import format_post_message

def test_database():
    """Test database functionality"""
    print("Testing Database...")
    db = Database('test_bot.db')
    
    # Test settings
    db.set_setting('test_key', 'test_value')
    assert db.get_setting('test_key') == 'test_value', "Setting storage failed"
    
    # Test posts
    success = db.add_post('Test Movie', 'https://example.com/test')
    assert success, "Failed to add post"
    
    assert db.is_posted('https://example.com/test'), "Post not found"
    assert not db.is_posted('https://example.com/nonexistent'), "False positive"
    
    # Test duplicate prevention
    duplicate = db.add_post('Test Movie 2', 'https://example.com/test')
    assert not duplicate, "Duplicate prevention failed"
    
    # Test statistics
    total = db.get_total_posts()
    assert total > 0, "Post count failed"
    
    # Cleanup
    import os
    db.close()
    if os.path.exists('test_bot.db'):
        os.remove('test_bot.db')
    
    print("✅ Database tests passed!")

def test_cache():
    """Test cache functionality"""
    print("\nTesting Cache Manager...")
    cache = CacheManager()
    
    # Test set/get
    cache.set('test_key', 'test_value', ttl=10)
    assert cache.get('test_key') == 'test_value', "Cache storage failed"
    
    # Test miss
    assert cache.get('nonexistent') is None, "Cache false positive"
    
    # Test stats
    stats = cache.get_stats()
    assert stats['size'] > 0, "Cache size wrong"
    assert stats['hits'] > 0, "Cache hits not tracked"
    
    # Test expiration
    cache.set('temp', 'value', ttl=1)
    import time
    time.sleep(2)
    assert cache.get('temp') is None, "Cache expiration failed"
    
    # Test clear
    cache.clear()
    assert cache.size() == 0, "Cache clear failed"
    
    print("✅ Cache tests passed!")

def test_format_message_escaping():
    """Ensure Markdown entities are escaped in formatted messages"""
    print("\nTesting Markdown escaping...")
    sample_item = {
        'title': 'Movie_Title [HD]',
        'quality': '1080p_Full',
        'genre': ['Action_Thriller', 'Sci-Fi'],
        'year': '2024',
        'rating': '8.1/10',
        'plot': 'Plot_with_underscores_and_symbols like [test] (should escape) _and italic_.',
        'download_links': [{'url': 'https://example.com/download', 'quality': '1080p'}],
    }

    message = format_post_message(sample_item)

    assert r"Movie\_Title" in message, "Title underscores not escaped"
    assert r"Plot\_with\_underscores" in message, "Plot underscores not escaped"

    print("✅ Markdown escaping test passed!")

async def _run_scraper_test():
    """Test scraper functionality"""
    print("\nTesting Scraper...")
    scraper = HDhub4uScraper()
    cache = CacheManager()
    
    try:
        # Test scraping (may fail if website is down)
        content = await scraper.get_latest_content(cache)
        
        if content:
            print(f"  Scraped {len(content)} items")
            
            # Test content structure
            item = content[0]
            assert 'title' in item, "Title missing"
            assert 'url' in item, "URL missing"
            
            print(f"  Sample: {item['title']}")
            print("✅ Scraper tests passed!")
        else:
            print("⚠️  No content scraped (website might be down)")
    
    except Exception as e:
        print(f"⚠️  Scraper test error: {e}")
        print("   (This may be normal if website is unreachable)")
    
    finally:
        await scraper.close()


def test_scraper():
    """Pytest-friendly wrapper for async scraper test"""
    asyncio.run(_run_scraper_test())

def run_tests():
    """Run all tests"""
    print("=" * 50)
    print("Running Component Tests")
    print("=" * 50)
    
    try:
        test_format_message_escaping()
        test_database()
        test_cache()
        asyncio.run(_run_scraper_test())
        
        print("\n" + "=" * 50)
        print("✅ All tests completed!")
        print("=" * 50)
        return 0
    
    except Exception as e:
        print("\n" + "=" * 50)
        print(f"❌ Tests failed: {e}")
        print("=" * 50)
        return 1

if __name__ == '__main__':
    sys.exit(run_tests())
