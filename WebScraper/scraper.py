from playwright.sync_api import sync_playwright

pw = sync_playwright().start()

browser = pw.firefox.launch(
    headless=False,
    slow_mo=2000
)

page = browser.new_page()
page.goto("https://ardes.bg")

gpus = page.locator("xpath=//a[contains(@href, 'video-karti')]")
page.goto(gpus.first.get_attribute("href"))

#print(page.content())
#print(page.title())

print(gpus.count())

browser.close()
#page.screenshot(path="example.com")
