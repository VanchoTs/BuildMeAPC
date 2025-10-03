import streamlit as st
from scrape import scrape_website, split_dom_content, clean_body_content, extract_body_content

def main():
    st.title("Basic AI Web Scraper")
    url = st.text_input("Website URL: ")
    
    if st.button("Scrape"):
        result = scrape_website(url)
        body_content = extract_body_content(result)
        cleaned_content = clean_body_content(body_content)
        st.session_state.dom_content = cleaned_content

        with st.expander("View DOM Content"):
            st.text_area("DOM Content", cleaned_content, height=300)
    
    if "dom_content" in st.session_state:
        parse_description = "Collect info about GPUs and compose a table showing their brand, chip maker, model and price"
        dom_chunks = split_dom_content(st.session_state.dom_content)

if __name__ == "__main__":
    main()
