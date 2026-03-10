import requests
import pandas as pd
import numpy as np
import time
from bs4 import BeautifulSoup
from prefect import task, flow


@task
def scrape_hills_cards():
    url = 'https://www.hillscards.co.uk/trading-card-games-c78/sealed-products-c92/decks-c97//pokemon-trading-card-game-m2'

    base_url = 'https://www.hillscards.co.uk/'

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    all_links = [base_url + x.find('a').get('href') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
    all_titles = [x.find('a').get('title') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
    next_ = soup.find('a', title='next')
    while next_:
        time.sleep(0.5)
        url = next_.get('href')
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        page_links = [base_url + x.find('a').get('href') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
        for link in page_links:
            all_links.append(link)
        page_titles = [x.find('a').get('title') for x in soup.find_all('div', class_="product__details__title product__details__title--branded")]
        for title in page_titles:
            all_titles.append(title)
        next_ = soup.find('a', title='next')
    
    dict_list = []
    for i in range(len(all_titles)):
        if all_titles[i][:7] != 'Pokemon':
            continue
        else:
            row_dict = {'title': all_titles[i][27:], 'url': all_links[i]}
            dict_list.append(row_dict)
    
    for row_dict in dict_list:
        time.sleep(20)
        url = row_dict['url']
        resp = requests.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        if soup.find('table'):
            row_dict['price'] = soup.find('table').find('span', class_="GBP").text.replace('\n','').strip()[1:]
        else:
            price = "N/A"


    hills_cards_df = pd.DataFrame(dict_list)
    hills_cards_df['source']='HillsCards'
    hills_cards_df['price']='N/A'
    return hills_cards_df


@task
def scrape_invicta():
    url = 'https://invictatcg.co.uk/product-category/pokemon-english/?wcf_search=true&_wcf_sortby=date&_wcf_categories=257&_wcf_page=1'
    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    other_links = soup.find_all('a', class_="woocommerce-LoopProduct-link woocommerce-loop-product__link")
    other_links = [x.get('href') for x in other_links]

    other_titles = [x.text for x in soup.find_all('h2')]

    other_prices = [x.text[1:] for x in soup.find_all('span', class_='price')]

    new_dict_list = []
    for i in range(len(other_titles)):
        row_dict = {'title': other_titles[i][9:], 'price': other_prices[i], 'url': other_links[i]}
        new_dict_list.append(row_dict)
    
    invicta_df = pd.DataFrame(new_dict_list)
    invicta_df['source']='Invicta'

    return invicta_df


@task
def scrape_total_cards():
    url = 'https://totalcards.net/collections/view-all-pokemon'
    base_url = 'https://totalcards.net'
    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    more_prices = [x.text[1:] for x in soup.find_all('div', class_="price-wrapper")]
    more_links = [base_url+x.get('href') for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
    more_titles = [x.text.replace('\n','').strip()[10:] for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]

    next_ = soup.find('a', class_='next')

    j=1
    while next_:
        print(j)
        time.sleep(0.5)
        url = base_url+next_.get('href')
        resp = requests.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        new_titles = [x.text.replace('\n','').strip()[10:] for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
        new_links = [base_url+x.get('href') for x in soup.find('div', id='CollectionProductGrid').find_all('a', class_='product-title alt-font')]
        new_prices = [x.text[1:] for x in soup.find_all('div', class_="price-wrapper")]
        for i in range(len(new_titles)):
            more_titles.append(new_titles[i])
            more_links.append(new_links[i])
            more_prices.append(new_prices[i])
        next_ = soup.find('a', class_='next')
        j+=1
    
    cleaned_prices = []
    for price in more_prices:
        print(price)
        if "\n" in price:
            print("Found space")
            price = price.split("\n")[0]
            print(f"New price: {price}")
        cleaned_prices.append(price)

    dict_list = []
    for i in range(len(more_titles)):
        row_dict = {'title': more_titles[i], 'price': cleaned_prices[i], 'url': more_links[i]}
        dict_list.append(row_dict)
        dict_list
    
    totalcard_df = pd.DataFrame(dict_list)
    totalcard_df['source'] = 'TotalCards'
    return totalcard_df


@task
def scrape_titan_cards():
    url = 'https://titancards.co.uk/collections/pokemon-sealed-products'
    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    titan_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
    titan_base_url = 'https://titancards.co.uk/'
    titan_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]

    titan_prices_raw = soup.find_all('div', class_="price__current")
    titan_prices = []
    for i in range(len(titan_prices_raw)):
        if i%2==0:
            titan_prices.append(titan_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
    
    next_ = soup.find('li', class_= "pagination--next")
    j = 1
    while next_:
        print(f"Page {j}...")
        next_url = titan_base_url + next_.find('a').get('href')
        resp = requests.get(next_url)
        resp.raise_for_status()
        soup=BeautifulSoup(resp.text, 'html.parser')
        new_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
        new_prices_raw = soup.find_all('div', class_="price__current")
        new_prices = []
        for i in range(len(new_prices_raw)):
            if i%2==0:
                new_prices.append(new_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
        new_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]
        for i in range(len(new_titles)):
            titan_titles.append(new_titles[i])
            titan_prices.append(new_prices[i])
            titan_urls.append(new_urls[i])
        next_ = soup.find('li', class_= "pagination--next")
        j += 1
    
    dict_list = []
    for i in range(len(titan_titles)):
        row_dict = {'title': titan_titles[i], 'price': titan_prices[i], 'url': titan_urls[i], 'source': 'TitanCards'}
        dict_list.append(row_dict)
        dict_list

    titan_df = pd.DataFrame(dict_list)

    url = 'https://titancards.co.uk/collections/pokemon-singles-uk'
    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    s_card_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]

    s_card_prices_raw = soup.find_all('div', class_="price__current")
    s_card_prices = []
    for i in range(len(s_card_prices_raw)):
        if i%2==0:
            s_card_prices.append(s_card_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
    
    s_card_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]

    next_ = soup.find('li', class_= "pagination--next")

    j = 1
    while next_:
        print(f"Page {j}...")
        next_url = titan_base_url + next_.find('a').get('href')
        resp = requests.get(next_url)
        resp.raise_for_status()
        soup=BeautifulSoup(resp.text, 'html.parser')
        new_titles = [x.find('a').text.replace('\n','').strip() for x in soup.find_all('h2', class_="productitem--title")]
        new_prices_raw = soup.find_all('div', class_="price__current")
        new_prices = []
        for i in range(len(new_prices_raw)):
            if i%2==0:
                new_prices.append(new_prices_raw[i].find('span', class_="money").text.replace('\n','').strip()[1:])
        new_urls = [titan_base_url + x.find('a').get('href') for x in soup.find_all('h2', class_="productitem--title")]
        for i in range(len(new_titles)):
            s_card_titles.append(new_titles[i])
            s_card_prices.append(new_prices[i])
            s_card_urls.append(new_urls[i])
        next_ = soup.find('li', class_= "pagination--next")
        j += 1

    dict_list = []
    for i in range(len(titan_titles)):
        row_dict = {'title': s_card_titles[i], 'price': s_card_prices[i], 'url': s_card_urls[i], 'source': 'TitanCards'}
        dict_list.append(row_dict)
    
    titan_s_card_df = pd.DataFrame(dict_list)

    titan_full_df = pd.concat(titan_df, titan_s_card_df)

    return titan_full_df


@task
def combine_dfs_and_save(*args):
    list_of_dfs = list(*args)
    full_df = pd.concat(list_of_dfs)

    full_df.to_csv('pokemon_cards_database.csv', index=False)


@flow
def run_pipeline():
    hills_df = scrape_hills_cards()
    invicta_df = scrpae_invicta()
    total_cards_df = scrape_total_cards()
    titan_df = scrape_titan_cards()

    combine_dfs_and_save(hills_df, invicta_df, total_cards_df, titan_df)


if __name__ == '__main__':
    run_pipeline.serve(name='collect_trading_card_data', cron="0 6 * * *")