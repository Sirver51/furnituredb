"""Per-site polite delay helper.

Call `polite_delay(site)` once before each outbound request to that site's
own pages/API. Image downloads are handled separately via aria2c and aren't
subject to this delay (except Homes R Us, whose images share the app host —
see aria2.py).
"""

import random
import time

# (min_seconds, max_seconds) per site, sleep a random amount in this range
# before each request to the site's own API/pages.
DELAY_RANGES = {
    "panhome": (0.6, 1.4),
    "homecentre": (0.6, 1.4),
    # homesrus robots.txt declares `Crawl-delay: 10` site-wide (pages + images,
    # same host). 0.6-1.4s is a deliberate, visible deviation from literal
    # compliance - bump toward 10s+ here if full compliance is preferred.
    "homesrus": (0.6, 1.4),
}


def polite_delay(site: str) -> None:
    lo, hi = DELAY_RANGES[site]
    time.sleep(random.uniform(lo, hi))
