import requests
import socks
import hashlib
import sqlite3
import smtplib
import schedule
import time
import json
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG for more detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
#        logging.FileHandler("page_monitor.log"),  # Log to file
        logging.StreamHandler()  # Log to console
    ]
)

# Load configuration from JSON file
try:
    with open('data/config.json', 'r') as f:
        config = json.load(f)
        logging.info("Configuration loaded successfully.")
except FileNotFoundError:
    logging.error("data/config.json not found. Exiting.")
    exit(1)
except json.JSONDecodeError:
    logging.error("Error parsing config.json. Exiting.")
    exit(1)

# Configuration
DB_FILE = 'data/page-history.db'
URLS = config['urls']
PROXY = config['proxy']
CHECK_INTERVAL = config['check_interval']
EMAIL_FROM = config['email']['from']
EMAIL_TO = config['email']['to']
EMAIL_SUBJECT = config['email']['subject']
SMTP_SERVER = config['email']['smtp_server']
SMTP_PORT = config['email']['smtp_port']
SMTP_USER = config['email']['smtp_user']
SMTP_PASSWORD = config['email']['smtp_password']

# Setup the SQLite database
def setup_database():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, hash TEXT)''')
        conn.commit()
        conn.close()
        logging.info(f"Database {DB_FILE} initialized.")
    except sqlite3.Error as e:
        logging.error(f"SQLite error: {e}")
        exit(1)

# Get the page content via SOCKS5 proxy
def get_page_content(url):
    proxies = {
        'http': f'socks5h://{PROXY}',
        'https': f'socks5h://{PROXY}',
    }
    try:
        response = requests.get(url, proxies=proxies)
        response.raise_for_status()
        logging.info(f"Successfully fetched content from {url}")
        return response.text
    except requests.RequestException as e:
        logging.error(f"Request error for {url}: {e}")
        return None

# Calculate hash for the page content
def calculate_hash(content):
    return 'x'+hashlib.sha256(content.encode('utf-8')).hexdigest()

# Store the hash in the database
def store_hash(url, hash):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO pages (url, hash) VALUES (?, ?)', (url, hash))
        conn.commit()
        conn.close()
        logging.info(f"Stored hash for {url}.")
    except sqlite3.Error as e:
        logging.error(f"SQLite error while storing hash for {url}: {e}")

# Retrieve the stored hash for a URL
def retrieve_hash(url):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT hash FROM pages WHERE url = ?', (url,))
        result = c.fetchone()
        conn.close()
        if result:
            logging.info(f"Retrieved hash for {url}.")
            return result[0]
        else:
            logging.info(f"No previous hash found for {url}.")
            return None
    except sqlite3.Error as e:
        logging.error(f"SQLite error while retrieving hash for {url}: {e}")
        return None

# Send an email notification
def send_email(url,content):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Subject'] = EMAIL_SUBJECT

    # Email body
    body = f'The content of the page at {url} has changed. See the attached HTML file for details.'
    msg.attach(MIMEText(body, 'plain'))

    # Create the HTML file
    html_filename = 'page_content.html'
    with open(html_filename, 'w', encoding='utf-8') as f:
        f.write(content)

    # Attach the HTML file
    with open(html_filename, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename={os.path.basename(html_filename)}',
        )
        msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_FROM, EMAIL_TO, text)
        server.quit()
        logging.info(f"Email sent to {EMAIL_TO} for URL {url}.")
    except smtplib.SMTPException as e:
        logging.error(f"Error sending email for {url}: {e}")
    finally:
        os.remove(html_filename)  # Clean up the temporary file

# Check each URL for changes
def check_urls():
    for url in URLS:
        content = get_page_content(url)
        if content is None:
            logging.warning(f"Skipping {url} due to previous errors.")
            continue

        current_hash = calculate_hash(content)
        stored_hash = retrieve_hash(url)

        if stored_hash and stored_hash != current_hash:
            store_hash(url, current_hash)
            logging.info(f"Content change detected for {url}.")
            send_email(url,content)

# Setup the schedule
def run_schedule():
    schedule.every(CHECK_INTERVAL).seconds.do(check_urls)
    logging.info(f"Starting scheduler with {CHECK_INTERVAL} seconds interval.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    setup_database()
    run_schedule()

