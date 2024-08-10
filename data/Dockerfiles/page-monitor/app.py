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
from datetime import datetime

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
SITES = config['sites']
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
        c.execute('''
            CREATE TABLE IF NOT EXISTS pages (
                url TEXT,
                hash TEXT,
                content TEXT,
                timestamp TEXT,
                PRIMARY KEY (url, timestamp)
            )
        ''')
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
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def store_content(url, hash, content):
    timestamp = datetime.utcnow().isoformat()
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO pages (url, hash, content, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (url, hash, content, timestamp))
        conn.commit()
        conn.close()
        logging.info(f"Stored content and hash for {url} at {timestamp}.")
    except sqlite3.Error as e:
        logging.error(f"SQLite error while storing content for {url}: {e}")

def retrieve_latest_hash(url):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            SELECT hash FROM pages
            WHERE url = ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (url,))
        result = c.fetchone()
        conn.close()
        if result:
            logging.info(f"Retrieved latest hash for {url}.")
            return result[0]
        else:
            logging.info(f"No previous hash found for {url}.")
            return None
    except sqlite3.Error as e:
        logging.error(f"SQLite error while retrieving latest hash for {url}: {e}")
        return None

# Send an email notification
def send_email(site,content):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Subject'] = EMAIL_SUBJECT

    # Email body
    body = f'The content of the page {site["name"]} at {site["url"]}has changed.\nSee the attached HTML file for details.'
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
        logging.info(f"Email sent to {EMAIL_TO} for site {site['name']}.")
    except smtplib.SMTPException as e:
        logging.error(f"Error sending email for {site['name']}: {e}")
    finally:
        os.remove(html_filename)  # Clean up the temporary file

# Check each URL for changes
def check_urls():
    for site in SITES:
        content = get_page_content(site['url'])
        if content is None:
            logging.warning(f"Skipping {site['name']} due to previous errors.")
            continue

        current_hash = calculate_hash(content)
        stored_hash = retrieve_latest_hash(site['url'])

        if not stored_hash:
            store_content(site['url'], current_hash, content)
            logging.info(f"Storing initial state for {site['name']}.")

        if stored_hash and stored_hash != current_hash:
            store_content(site['url'], current_hash, content)
            logging.info(f"Content change detected for {site['name']}.")
            send_email(site,content)

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

