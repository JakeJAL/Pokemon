import requests
import pandas as pd
import numpy as np
import time
from bs4 import BeautifulSoup
from prefect import task, flow
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import random
from requests.exceptions import RequestException, Timeout, ConnectionError
from typing import Optional, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def retry_request(url: str, max_retries: int = 3, initial_wait: int = 2, timeout: int = 10) -> Optional[requests.Response]:
    """
    Robust request function with exponential backoff retry logic.
    
    Args:
        url: URL to request
        max_retries: Maximum number of retry attempts
        initial_wait: Initial wait time in seconds (doubles with each retry)
        timeout: Request timeout in seconds
        
    Returns:
        Response object if successful, None if all retries failed
    """
    wait_time = initial_wait
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Requesting {url} (attempt {attempt + 1}/{max_retries})")
            resp = requests.get(url, timeout=timeout)
            
            # Handle specific status codes
            if resp.status_code == 503:
                logger.warning(f"503 Service Unavailable for {url}. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                wait_time *= 2  # Exponential backoff
                continue
            elif resp.status_code == 429:
                logger.warning(f"429 Too Many Requests for {url}. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                wait_time *= 2
                continue
            elif resp.status_code >= 500:
                logger.warning(f"Server error {resp.status_code} for {url}. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                wait_time *= 2
                continue
            
            resp.raise_for_status()
            logger.info(f"Successfully retrieved {url}")
            return resp
            
        except Timeout:
            logger.warning(f"Timeout for {url}. Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
            wait_time *= 2
        except ConnectionError:
            logger.warning(f"Connection error for {url}. Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
            wait_time *= 2
        except RequestException as e:
            logger.warning(f"Request exception for {url}: {e}. Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
            wait_time *= 2
    
    logger.error(f"Failed to retrieve {url} after {max_retries} attempts. Skipping.")
    return None


@task
def scrape_hills_cards():
    """Scrape Hills Cards with robust error handling"""
    try:
        url = 'https://www.hillscards.co.uk/trading-card-games-c78/sealed-products-c92/decks-c97//pokemon-trading-card-game-m2'
        base_url = 'https://www.hillscards.co.uk/'

        resp = retry_request(url)
        if not resp:
            logger.error("Failed to retrieve initial Hills Cards page. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'url', 'price', 'source'])
        
        soup = BeautifulSoup(resp.text, 'html.parser')

        all_links = []
        all_titles = []
        
        try:
            all_links = [base_url + x.find('a').get('href') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
            all_titles = [x.find('a').get('title') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
        except Exception as e:
            logger.error(f"Error parsing Hills Cards initial page: {e}")
            return pd.DataFrame(columns=['title', 'url', 'price', 'source'])
        
        next_ = soup.find('a', title='next')
        page_num = 1
        
        while next_:
            time.sleep(0.5)
            url = next_.get('href')
            page_num += 1
            logger.info(f"Scraping Hills Cards page {page_num}")
            
            resp = retry_request(url)
            if not resp:
                logger.warning(f"Failed to retrieve Hills Cards page {page_num}. Moving to next step.")
                break
            
            try:
                soup = BeautifulSoup(resp.text, 'html.parser')
                page_links = [base_url + x.find('a').get('href') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
                page_titles = [x.find('a').get('title') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
                
                all_links.extend(page_links)
                all_titles.extend(page_titles)
                next_ = soup.find('a', title='next')
            except Exception as e:
                logger.error(f"Error parsing Hills Cards page {page_num}: {e}. Skipping to next page.")
                next_ = None
        
        dict_list = []
        for i in range(len(all_titles)):
            if all_titles[i][:7] != 'Pokemon':
                continue
            else:
                row_dict = {'title': all_titles[i][27:], 'url': all_links[i], 'price': 'Check for price'}
                dict_list.append(row_dict)
        
        # Scrape individual product pages for prices
        for idx, row_dict in enumerate(dict_list):
            time.sleep(15)  # Be respectful to the server
            url = row_dict['url']
            logger.info(f"Scraping price for product {idx + 1}/{len(dict_list)}")
            
            resp = retry_request(url)
            if not resp:
                logger.warning(f"Failed to retrieve price for {url}. Setting price to 'Check for price'")
                continue
            
            try:
                soup = BeautifulSoup(resp.text, 'html.parser')
                if soup.find('table'):
                    price_elem = soup.find('table').find('span', class_="GBP")
                    if price_elem:
                        row_dict['price'] = price_elem.text.replace('\n','').strip()[1:]
            except Exception as e:
                logger.warning(f"Error parsing price for {url}: {e}. Setting price to 'Check for price'")

        hills_cards_df = pd.DataFrame(dict_list)
        hills_cards_df['source'] = 'HillsCards'
        logger.info(f"Successfully scraped {len(hills_cards_df)} items from Hills Cards")
        return hills_cards_df
        
    except Exception as e:
        logger.error(f"Unexpected error in scrape_hills_cards: {e}. Returning empty DataFrame.")
        return pd.DataFrame(columns=['title', 'url', 'price', 'source'])


@task
def scrape_invicta():
    """Scrape Invicta TCG with robust error handling"""
    try:
        url = 'https://invictatcg.co.uk/product-category/pokemon-english/?wcf_search=true&_wcf_sortby=date&_wcf_categories=257&_wcf_page=1'
        
        resp = retry_request(url)
        if not resp:
            logger.error("Failed to retrieve Invicta page. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])
        
        soup = BeautifulSoup(resp.text, 'html.parser')

        try:
            other_links = soup.find_all('a', class_="woocommerce-LoopProduct-link woocommerce-loop-product__link")
            other_links = [x.get('href') for x in other_links]
            other_titles = [x.text for x in soup.find_all('h2')]
            other_prices = [x.text[1:] for x in soup.find_all('span', class_='price')]

            new_dict_list = []
            for i in range(len(other_titles)):
                row_dict = {'title': other_titles[i][9:], 'price': other_prices[i], 'url': other_links[i]}
                new_dict_list.append(row_dict)
            
            invicta_df = pd.DataFrame(new_dict_list)
            invicta_df['source'] = 'Invicta'
            logger.info(f"Successfully scraped {len(invicta_df)} items from Invicta")
            return invicta_df
            
        except Exception as e:
            logger.error(f"Error parsing Invicta page: {e}. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])
            
    except Exception as e:
        logger.error(f"Unexpected error in scrape_invicta: {e}. Returning empty DataFrame.")
        return pd.DataFrame(columns=['title', 'price', 'url', 'source'])


@task
def scrape_total_cards():
    """Scrape Total Cards with robust error handling"""
    try:
        url = 'https://totalcards.net/collections/view-all-pokemon'
        base_url = 'https://totalcards.net'
        
        resp = retry_request(url)
        if not resp:
            logger.error("Failed to retrieve Total Cards initial page. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])
        
        soup = BeautifulSoup(resp.text, 'html.parser')

        more_prices = []
        more_links = []
        more_titles = []
        
        try:
            more_prices = [x.text[1:] for x in soup.find_all('div', class_="price-wrapper")]
            more_links = [base_url+x.get('href') for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
            more_titles = [x.text.replace('\n','').strip()[10:] for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
        except Exception as e:
            logger.error(f"Error parsing Total Cards initial page: {e}. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])

        next_ = soup.find('a', class_='next')
        page_num = 1

        while next_:
            page_num += 1
            logger.info(f"Scraping Total Cards page {page_num}")
            time.sleep(0.5)
            url = base_url + next_.get('href')
            
            resp = retry_request(url)
            if not resp:
                logger.warning(f"Failed to retrieve Total Cards page {page_num}. Moving to next step.")
                break
            
            try:
                soup = BeautifulSoup(resp.text, 'html.parser')
                new_titles = [x.text.replace('\n','').strip()[10:] for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
                new_links = [base_url+x.get('href') for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
                new_prices = [x.text[1:] for x in soup.find_all('div', class_="price-wrapper")]
                
                more_titles.extend(new_titles)
                more_links.extend(new_links)
                more_prices.extend(new_prices)
                next_ = soup.find('a', class_='next')
            except Exception as e:
                logger.error(f"Error parsing Total Cards page {page_num}: {e}. Skipping to next page.")
                next_ = None
        
        # Clean prices
        cleaned_prices = []
        for price in more_prices:
            if "\n" in price:
                price = price.split("\n")[0]
            cleaned_prices.append(price)

        dict_list = []
        for i in range(len(more_titles)):
            row_dict = {'title': more_titles[i], 'price': cleaned_prices[i], 'url': more_links[i]}
            dict_list.append(row_dict)
        
        totalcard_df = pd.DataFrame(dict_list)
        totalcard_df['source'] = 'TotalCards'
        logger.info(f"Successfully scraped {len(totalcard_df)} items from Total Cards")
        return totalcard_df
        
    except Exception as e:
        logger.error(f"Unexpected error in scrape_total_cards: {e}. Returning empty DataFrame.")
        return pd.DataFrame(columns=['title', 'price', 'url', 'source'])


@task
def scrape_titan_cards():
    """Scrape Titan Cards with robust error handling"""
    try:
        url = 'https://titancards.co.uk/collections/pokemon-sealed-products'
        titan_base_url = 'https://titancards.co.uk/'
        
        resp = retry_request(url)
        if not resp:
            logger.error("Failed to retrieve Titan Cards initial page. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])
        
        soup = BeautifulSoup(resp.text, 'html.parser')

        titan_titles = []
        titan_urls = []
        titan_prices = []
        
        try:
            titan_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
            titan_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]
            titan_prices_raw = soup.find_all('div', class_="price__current")
            for i in range(len(titan_prices_raw)):
                if i%2==0:
                    titan_prices.append(titan_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
        except Exception as e:
            logger.error(f"Error parsing Titan Cards initial page: {e}. Returning empty DataFrame.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])
        
        next_ = soup.find('li', class_="pagination--next")
        page_num = 1
        
        while next_:
            page_num += 1
            logger.info(f"Scraping Titan Cards sealed products page {page_num}")
            next_url = titan_base_url + next_.find('a').get('href')
            
            resp = retry_request(next_url)
            if not resp:
                logger.warning(f"Failed to retrieve Titan Cards page {page_num}. Moving to next step.")
                break
            
            try:
                soup = BeautifulSoup(resp.text, 'html.parser')
                new_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
                new_prices_raw = soup.find_all('div', class_="price__current")
                new_prices = []
                for i in range(len(new_prices_raw)):
                    if i%2==0:
                        new_prices.append(new_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
                new_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]
                
                titan_titles.extend(new_titles)
                titan_prices.extend(new_prices)
                titan_urls.extend(new_urls)
                next_ = soup.find('li', class_="pagination--next")
            except Exception as e:
                logger.error(f"Error parsing Titan Cards page {page_num}: {e}. Skipping to next page.")
                next_ = None

        dict_list = []
        for i in range(len(titan_titles)):
            row_dict = {'title': titan_titles[i], 'price': titan_prices[i], 'url': titan_urls[i], 'source': 'TitanCards'}
            dict_list.append(row_dict)

        titan_df = pd.DataFrame(dict_list)

        # Scrape singles
        url = 'https://titancards.co.uk/collections/pokemon-singles-uk'
        resp = retry_request(url)
        if not resp:
            logger.warning("Failed to retrieve Titan Cards singles page. Returning sealed products only.")
            return titan_df
        
        soup = BeautifulSoup(resp.text, 'html.parser')

        s_card_titles = []
        s_card_prices = []
        s_card_urls = []
        
        try:
            s_card_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
            s_card_prices_raw = soup.find_all('div', class_="price__current")
            for i in range(len(s_card_prices_raw)):
                if i%2==0:
                    s_card_prices.append(s_card_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
            s_card_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]
        except Exception as e:
            logger.error(f"Error parsing Titan Cards singles initial page: {e}. Returning sealed products only.")
            return titan_df

        next_ = soup.find('li', class_="pagination--next")
        page_num = 1

        while next_:
            page_num += 1
            logger.info(f"Scraping Titan Cards singles page {page_num}")
            next_url = titan_base_url + next_.find('a').get('href')
            
            resp = retry_request(next_url)
            if not resp:
                logger.warning(f"Failed to retrieve Titan Cards singles page {page_num}. Moving to next step.")
                break
            
            try:
                soup = BeautifulSoup(resp.text, 'html.parser')
                new_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
                new_prices_raw = soup.find_all('div', class_="price__current")
                new_prices = []
                for i in range(len(new_prices_raw)):
                    if i%2==0:
                        new_prices.append(new_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
                new_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]
                
                s_card_titles.extend(new_titles)
                s_card_prices.extend(new_prices)
                s_card_urls.extend(new_urls)
                next_ = soup.find('li', class_="pagination--next")
            except Exception as e:
                logger.error(f"Error parsing Titan Cards singles page {page_num}: {e}. Skipping to next page.")
                next_ = None

        dict_list = []
        for i in range(len(s_card_titles)):
            row_dict = {'title': s_card_titles[i], 'price': s_card_prices[i], 'url': s_card_urls[i], 'source': 'TitanCards'}
            dict_list.append(row_dict)
        
        titan_s_card_df = pd.DataFrame(dict_list)
        titan_full_df = pd.concat([titan_df, titan_s_card_df], ignore_index=True)
        logger.info(f"Successfully scraped {len(titan_full_df)} items from Titan Cards")
        return titan_full_df
        
    except Exception as e:
        logger.error(f"Unexpected error in scrape_titan_cards: {e}. Returning empty DataFrame.")
        return pd.DataFrame(columns=['title', 'price', 'url', 'source'])


@task
def scrape_ebay():
    """Scrape eBay with robust error handling"""
    try:
        PAGES_TO_SCRAPE = 200
        titles_list = []
        prices_list = []
        urls_list = []

        driver = None
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {e}. Skipping eBay scraping.")
            return pd.DataFrame(columns=['title', 'price', 'url', 'source'])

        try:
            url = "https://www.ebay.co.uk/sch/2536/i.html?_nkw=pokemon+cards&_from=R40&Card%2520Type=Pok%25C3%25A9mon&Language=English&_dcat=183454"
            driver.get(url)

            for page in range(PAGES_TO_SCRAPE):
                logger.info(f"Scraping eBay page {page + 1}/{PAGES_TO_SCRAPE}")
                
                try:
                    wait = WebDriverWait(driver, 15)
                    wait.until(EC.presence_of_element_located((By.ID, "srp-river-results")))
                    
                    results_container = driver.find_element(By.ID, "srp-river-results")
                    listings = results_container.find_elements(By.CSS_SELECTOR, ".s-item__wrapper, .su-card-container")

                    for item in listings:
                        try:
                            title_el = item.find_element(By.CSS_SELECTOR, 'div[role="heading"] span.su-styled-text')
                            title_text = title_el.get_attribute("innerText").strip()
                            
                            if not title_text or "Shop on eBay" in title_text:
                                continue

                            link_el = item.find_element(By.CSS_SELECTOR, "a[href*='/itm/']")
                            price_el = item.find_element(By.CSS_SELECTOR, ".s-item__price, .su-card__price, span.bold")

                            titles_list.append(title_text)
                            urls_list.append(link_el.get_attribute("href"))
                            prices_list.append(price_el.get_attribute("innerText").strip()[1:])
                        except:
                            continue

                    logger.info(f"Total eBay items so far: {len(titles_list)}")

                    # Pagination
                    if page < PAGES_TO_SCRAPE - 1:
                        try:
                            next_selectors = [
                                "a[aria-label='Go to next search page']",
                                "a[type='next']",
                                ".pagination__next",
                                ".s-pagination__next"
                            ]
                            
                            next_button = None
                            for selector in next_selectors:
                                try:
                                    next_button = driver.find_element(By.CSS_SELECTOR, selector)
                                    if next_button.is_enabled():
                                        break
                                except:
                                    continue

                            if next_button:
                                driver.execute_script("arguments[0].scrollIntoView();", next_button)
                                time.sleep(1)
                                next_button.click()
                                time.sleep(random.uniform(3, 5))
                            else:
                                logger.info("Next button not found on eBay page. Ending pagination.")
                                break
                                
                        except Exception as e:
                            logger.warning(f"eBay pagination error on page {page + 1}: {e}. Ending pagination.")
                            break
                            
                except Exception as e:
                    logger.error(f"Error scraping eBay page {page + 1}: {e}. Skipping to next page.")
                    continue

            ebay_df = pd.DataFrame({
                'title': titles_list,
                'price': prices_list,
                'url': urls_list
            })
            ebay_df['source'] = 'eBay'
            logger.info(f"Successfully scraped {len(ebay_df)} items from eBay")
            return ebay_df

        finally:
            if driver:
                driver.quit()
                
    except Exception as e:
        logger.error(f"Unexpected error in scrape_ebay: {e}. Returning empty DataFrame.")
        return pd.DataFrame(columns=['title', 'price', 'url', 'source'])


@task
def combine_dfs_and_save(*args):
    """Combine all DataFrames and save to CSV"""
    try:
        list_of_dfs = [df for df in args if not df.empty]
        
        if not list_of_dfs:
            logger.error("No data to save. All scrapers returned empty DataFrames.")
            return
        
        full_df = pd.concat(list_of_dfs, ignore_index=True)
        full_df.to_csv('pokemon_cards_database.csv', index=False)
        logger.info(f"Successfully saved {len(full_df)} total items to pokemon_cards_database.csv")
        
    except Exception as e:
        logger.error(f"Error combining and saving DataFrames: {e}")


@flow
def run_pipeline():
    """Main pipeline flow with error handling"""
    logger.info("Starting Pokemon card scraping pipeline")
    
    hills_df = scrape_hills_cards()
    invicta_df = scrape_invicta()
    total_cards_df = scrape_total_cards()
    titan_df = scrape_titan_cards()
    ebay_df = scrape_ebay()
    
    combine_dfs_and_save(hills_df, invicta_df, total_cards_df, titan_df, ebay_df)
    
    logger.info("Pipeline completed")


if __name__ == '__main__':
    run_pipeline.serve(name='collect_trading_card_data', cron="0 6 * * *")