import selenium.webdriver as webdriver
from selenium.webdriver.chrome.service import Service
import time
from bs4 import BeautifulSoup

def scrape_website(site):
    browser_driver_path = "./geckodriver.exe"
    options= webdriver.FirefoxOptions()
    driver = webdriver.Firefox(service=Service(browser_driver_path), options=options)

    try:
        driver.get(site)
        html = driver.page_source
        time.sleep(10)

        return html
    
    finally:
        driver.quit()

def extract_body_content(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    body_content = soup.body
    if body_content:
        return str(body_content)
    return ""

def clean_body_content(body_content):
    soup = BeautifulSoup(body_content, "html.parser")

    for script_or_style in soup(["script", "style"]):
        script_or_style.extract()

    clened_content = soup.get_text(separator="\n")
    clened_content = "\n".join(line.strip() for line in clened_content.splitlines() if line.strip())

    return clened_content

def split_dom_content(dom_content, max_lenght=6000):
    return [
        dom_content[i:i+max_lenght] for i in range(0, len(dom_content), max_lenght)
    ]
