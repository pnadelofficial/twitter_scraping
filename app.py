import streamlit as st
from twitter_scraper import TwitterScraper

search_query = st.text_input("Search query")
from_account = st.text_input("From account")

if search_query and from_account:
    date_toggle = st.checkbox("Enable date range")
    if date_toggle:
        start_date = st.date_input("Start date")
        end_date = st.date_input("End date")
        scraper = TwitterScraper(search_query, from_account, start_date, end_date)
    else:
        scraper = TwitterScraper(search_query, from_account)
        
    if st.button("Scrape"):
        scraper.setup_driver()
        scraper.load_cookies("cookies.json")
        articles = scraper.scrape(save_screenshots=False)
        df = scraper.format_articles()
        
        @st.cache_data
        def convert_df(df):
            return df.to_csv(index=False).encode('utf-8')  
        csv = convert_df(df)
        st.download_button(
            label="Download data as CSV",
            data=csv,
            file_name='data.csv',
            mime='text/csv'
        )
