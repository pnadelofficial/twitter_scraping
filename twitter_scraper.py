import time
from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    NoSuchElementException
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import logging
from datetime import datetime
from collections import OrderedDict
from urllib.parse import quote
from typing import Optional
import pandas as pd
from bs4 import BeautifulSoup
import uuid

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TwitterScraper:
    def __init__(
            self,
            search_query: str,
            from_account: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            scroll_pause_time:int=3, 
            initial_wait:int=7,
            scroll_attempt_limit:int=5,
            scroll_pixel_increment:int=1000
        ):
        self.search_query = search_query
        self.from_account = from_account
        self.start_date = start_date
        self.end_date = end_date
        self.scroll_pause_time = scroll_pause_time
        self.initial_wait = initial_wait
        self.scroll_attempt_limit = scroll_attempt_limit
        self.scroll_pixel_increment = scroll_pixel_increment
        self.driver = None
        self.article_htmls = OrderedDict()
        self.last_height = 0
        
    def _construct_search_url(self) -> str:
        """Construct the search URL with all parameters."""
        query_parts = [self.search_query]
        
        if self.from_account:
            query_parts.append(f"(from:{self.from_account})")
        
        if self.start_date:
            query_parts.append(f"since:{self.start_date}")
            
        if self.end_date:
            query_parts.append(f"until:{self.end_date}")
        
        query_string = " ".join(query_parts)
        encoded_query = quote(query_string)
        return f"https://x.com/search?q={encoded_query}&f=live"
    
    def setup_driver(self):
        """Initialize and setup the Chrome driver"""
        chrome_options = webdriver.ChromeOptions()
        # chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-popup-blocking")

        self.driver = webdriver.Chrome(options=chrome_options)
        search_url = self._construct_search_url()
        logging.info(f"Loading search URL: {search_url}")
        self.driver.get(search_url)
        
    def load_cookies(self, cookie_file):
        """Load and add cookies from a JSON file"""
        try:
            with open(cookie_file, 'r') as f:
                cookies = json.load(f)
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    logging.warning(f"Failed to add cookie {cookie.get('name')}: {str(e)}")
            self.driver.refresh()
            self.driver.get(self._construct_search_url())
        except FileNotFoundError:
            logging.error(f"Cookie file {cookie_file} not found")
            raise
            
    def wait_for_elements(self, by, value, timeout=10):
        """Wait for elements to be present on the page"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_all_elements_located((by, value))
            )
        except TimeoutException:
            logging.warning(f"Timeout waiting for elements: {value}")
            return []
            
    def scroll_page(self) -> bool:
        """
        Enhanced scrolling with multiple attempt and checks.
        Returns True if new content was loaded, False otherwise.
        """
        initial_height = self.driver.execute_script("return document.documentElement.scrollHeight")

        # Try different scroll amounts
        scroll_amounts = [
            self.scroll_pixel_increment,  # Normal scroll
            self.scroll_pixel_increment * 2,  # Larger scroll
            self.scroll_pixel_increment // 2  # Smaller scroll
        ]

        for scroll_amount in scroll_amounts:
            # Scroll and wait
            self.driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            time.sleep(self.scroll_pause_time)
            
            # Check for new content
            new_height = self.driver.execute_script("return document.documentElement.scrollHeight")
            if new_height > initial_height:
                return True
                
            # Try to trigger lazy loading
            self.driver.execute_script("""
                window.dispatchEvent(new Event('scroll'));
                window.dispatchEvent(new Event('wheel'));
            """)
            time.sleep(1)
        
        return False
            
    def collect_articles(self):
        """Collect all articles from the current page"""
        try:
            articles = self.wait_for_elements(By.TAG_NAME, "article")
            for article in articles:
                try:
                    html_content = article.get_attribute("innerHTML")
                    if not html_content:
                        continue
                    
                    try:
                        time_element = article.find_element(By.TAG_NAME, "time")
                        tweet_time = time_element.get_attribute("datetime")
                        key = tweet_time
                    except NoSuchElementException:
                        key = html_content
                    
                    if key not in self.article_htmls:
                        self.article_htmls[key] = {
                            "html": html_content,
                            "timestamp": tweet_time if 'tweet_time' in locals() else None # this wild
                        }
                except StaleElementReferenceException:
                    continue
        except Exception as e:
            logging.error(f"Error collecting articles: {str(e)}")
            
    def save_progress(self):
        """Save scraped data to a file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"./output/twitter_search_{timestamp}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            for article_data in self.article_htmls.values():
                f.write(f"Timestamp: {article_data['timestamp']}\n")
                f.write(f"{article_data['html']}\n---\n")
        logging.info(f"Saved {len(self.article_htmls)} articles to {filename}")
            
    def scrape(self, max_scrolls=None, save_screenshots=False, new_content_retries=3):
        """Main scraping method"""
        try:
            # Initial page setup
            logging.info(f"Starting search for: {self.search_query}")
            time.sleep(self.initial_wait)
            
            scroll_count = 0
            no_new_content_count = 0
            
            while True:
                if max_scrolls and scroll_count >= max_scrolls:
                    logging.info("Reached maximum scroll limit")
                    break
                    
                prev_count = len(self.article_htmls)
                self.collect_articles()
                
                if save_screenshots:
                    self.driver.save_screenshot(f'scroll_{scroll_count}.png')
                
                if len(self.article_htmls) == prev_count:
                    no_new_content_count += 1
                    if no_new_content_count >= new_content_retries:  # Try this many times before giving up
                        logging.info("No new content found after multiple attempts")
                        break
                else:
                    no_new_content_count = 0
                
                if not self.scroll_page():
                    logging.info("Reached end of page or no new content loaded")

                    # One final check for new content
                    self.collect_articles()
                    if len(self.article_htmls) == prev_count:
                        logging.info("No new content found after final check")
                        break
                
                scroll_count += 1
                logging.info(f"Scroll {scroll_count}: Found {len(self.article_htmls)} unique articles")
                
            self.save_progress()
            
        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise
        finally:
            if self.driver:
                self.driver.quit()

        self.sorted_articles = sorted(
            self.article_htmls.values(),
            key=lambda x: x['timestamp'] if x['timestamp'] else ''
        )
        return [article['html'] for article in self.sorted_articles]
        
    def format_articles(self) -> pd.DataFrame:
        """Format the scraped articles as a DataFrame"""
        data = []

        def get_relevant_info(soup: BeautifulSoup) -> tuple:
            post_text = soup.get_text()
            
            poss_img = soup.find_all('img', attrs={'class':'css-9pa8cd'})
            if len(poss_img) > 1:
                img_html = poss_img[1]
                image_url = img_html['src']
            else:
                image_url = None
            return post_text, image_url
    

        for d in self.sorted_articles:
            date = d['timestamp']
            article = d['html']
            name = str(uuid.uuid4())
            soup = BeautifulSoup(article, features="html.parser")
            post_text, image_url = get_relevant_info(soup)
            data.append((name, date, post_text, image_url))
        
        return pd.DataFrame(data, columns=['ID', 'Date', 'Post Text', 'Image URL'])