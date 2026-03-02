"""Shadowban and restriction detection."""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine safely from any context.

    Works whether called from a thread with no loop, or inside a running loop.
    Never crashes with 'event loop already running'.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    else:
        return asyncio.run(coro)


class BanDetector:
    """Detects shadowbans and restrictions on Reddit and Twitter."""

    def check_reddit_shadowban(self, reddit_instance, username: str) -> Dict:
        """Check for Reddit shadowban indicators."""
        result = {
            "is_shadowbanned": False,
            "indicators": [],
            "confidence": "low",
        }

        try:
            user = reddit_instance.redditor(username)
            comments = list(user.comments.new(limit=10))

            # No comments is NOT a shadowban indicator for new/quiet accounts
            if not comments:
                logger.debug(f"u/{username}: no comments found (new/quiet account)")
                return result

            # Need enough samples for reliable detection
            if len(comments) < 3:
                logger.debug(f"u/{username}: only {len(comments)} comments, skipping check")
                return result

            low_score_count = sum(1 for c in comments if c.score <= 1)
            if low_score_count == len(comments):
                result["indicators"].append(
                    "All recent comments have score <= 1"
                )

            # Check if comments are hidden (404/removed, NOT network errors)
            hidden_count = 0
            for comment in comments[:5]:
                try:
                    comment.refresh()
                except Exception as e:
                    err_str = str(e).lower()
                    if "404" in err_str or "not found" in err_str or "removed" in err_str:
                        hidden_count += 1
                    else:
                        logger.debug(f"Comment refresh non-ban error: {e}")

            if hidden_count >= 2:
                result["indicators"].append(
                    f"{hidden_count}/{min(len(comments), 5)} comments appear hidden"
                )

            # Require 2+ STRONG indicators for shadowban detection
            if len(result["indicators"]) >= 2:
                result["is_shadowbanned"] = True
                result["confidence"] = "high"
            elif len(result["indicators"]) == 1:
                result["confidence"] = "low"

        except Exception as e:
            logger.error(f"Shadowban check failed for u/{username}: {e}")
            # API errors are NOT indicators — return inconclusive

        return result

    def check_twitter_restriction(self, client, username: str) -> Dict:
        """Check for Twitter account restrictions. Safe for sync/async contexts."""
        result = {
            "is_restricted": False,
            "indicators": [],
        }

        try:
            import asyncio

            async def _check():
                tweets = await client.search_tweet(
                    f"from:{username}", product="Latest"
                )
                return list(tweets) if tweets else []

            tweets = _run_async(_check())

            if not tweets:
                result["indicators"].append("No own tweets found in search")
                # Don't immediately mark restricted — could be indexing delay
                logger.debug(f"@{username}: no tweets in search (may be delay)")

        except Exception as e:
            logger.error(f"Twitter restriction check failed for @{username}: {e}")
            # API errors are NOT restriction indicators

        return result
