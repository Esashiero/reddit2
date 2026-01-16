import os
import praw
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

REDDIT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_AGENT = os.getenv("REDDIT_USER_AGENT")

print(f"ID: {REDDIT_ID[:5]}...")
print(f"Agent: {REDDIT_AGENT}")

reddit = praw.Reddit(
    client_id=REDDIT_ID, client_secret=REDDIT_SECRET, user_agent=REDDIT_AGENT
)

try:
    query = '("brother")'
    sub = "relationship_advice"
    print(f"Searching r/{sub} for '{query}'...")
    subreddit = reddit.subreddit(sub)
    for post in subreddit.search(query, limit=5):
        print(f"Found: {post.title}")
except Exception as e:
    print(f"Error: {e}")
