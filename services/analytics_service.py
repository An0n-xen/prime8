"""Analytics engine: growth calculator, breakout detector, health scorer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from utils.logger import get_logger

logger = get_logger(__name__)


class GrowthCalculator:
    """Computes growth rate, absolute growth, and velocity from star snapshots."""

    @staticmethod
    def compute(snapshots: list[dict]) -> dict:
        if len(snapshots) < 2:
            return {
                "growth_1d": 0, "growth_7d": 0, "growth_30d": 0,
                "rate_7d": 0.0, "rate_30d": 0.0,
                "velocity": 1.0, "velocity_label": "insufficient data",
                "current_stars": snapshots[-1]["stars"] if snapshots else 0,
            }

        now = datetime.now(UTC)
        current = snapshots[-1]["stars"]

        def stars_at_offset(days: int) -> int | None:
            target = now - timedelta(days=days)
            closest = None
            for s in snapshots:
                snap_time = datetime.fromisoformat(s["snapshot_at"].replace("Z", "+00:00"))
                if snap_time <= target:
                    closest = s["stars"]
            return closest

        stars_1d_ago = stars_at_offset(1)
        stars_7d_ago = stars_at_offset(7)
        stars_14d_ago = stars_at_offset(14)
        stars_30d_ago = stars_at_offset(30)

        growth_1d = current - stars_1d_ago if stars_1d_ago is not None else 0
        growth_7d = current - stars_7d_ago if stars_7d_ago is not None else 0
        growth_30d = current - stars_30d_ago if stars_30d_ago is not None else 0

        rate_7d = (growth_7d / stars_7d_ago * 100) if stars_7d_ago and stars_7d_ago > 0 else 0.0
        rate_30d = (growth_30d / stars_30d_ago * 100) if stars_30d_ago and stars_30d_ago > 0 else 0.0

        # Velocity: compare this week's daily avg to last week's
        velocity = 1.0
        velocity_label = "steady"
        if stars_7d_ago is not None and stars_14d_ago is not None:
            daily_avg_this_week = growth_7d / 7 if growth_7d else 0
            growth_prev_week = (stars_7d_ago - stars_14d_ago) if stars_14d_ago else 0
            daily_avg_last_week = growth_prev_week / 7 if growth_prev_week else 0

            if daily_avg_last_week > 0:
                velocity = round(daily_avg_this_week / daily_avg_last_week, 2)
                if velocity > 1.2:
                    velocity_label = "accelerating"
                elif velocity < 0.8:
                    velocity_label = "decelerating"
                else:
                    velocity_label = "steady"

        return {
            "growth_1d": growth_1d,
            "growth_7d": growth_7d,
            "growth_30d": growth_30d,
            "rate_7d": round(rate_7d, 2),
            "rate_30d": round(rate_30d, 2),
            "velocity": velocity,
            "velocity_label": velocity_label,
            "current_stars": current,
            "daily_avg_7d": round(growth_7d / 7, 1) if growth_7d else 0,
        }


class BreakoutDetector:
    """Detects repos experiencing abnormal spikes in star activity."""

    @staticmethod
    def check(snapshots: list[dict], multiplier: float = 3.0) -> dict | None:
        if len(snapshots) < 3:
            return None

        # Calculate daily gains
        daily_gains = []
        for i in range(1, len(snapshots)):
            gain = snapshots[i]["stars"] - snapshots[i - 1]["stars"]
            daily_gains.append(max(gain, 0))

        if not daily_gains:
            return None

        today_gain = daily_gains[-1]
        if len(daily_gains) < 2:
            return None

        # Rolling average excluding today
        historical = daily_gains[:-1]
        rolling_avg = sum(historical) / len(historical) if historical else 0

        # Skip if baseline is too low (avoid false positives from noise)
        if rolling_avg < 5 and today_gain < 20:
            return None

        # Check against multiplier
        effective_avg = max(rolling_avg, 1)  # avoid division by zero
        ratio = today_gain / effective_avg

        if ratio >= multiplier:
            severity = "notable"
            if ratio >= 10:
                severity = "explosive"
            elif ratio >= 5:
                severity = "major breakout"
            elif ratio >= 3:
                severity = "significant"
            elif ratio >= 2:
                severity = "notable"

            return {
                "today_gain": today_gain,
                "rolling_avg": round(rolling_avg, 1),
                "ratio": round(ratio, 1),
                "severity": severity,
                "multiplier_used": multiplier,
            }

        return None


class HealthScorer:
    """Aggregates multiple signals into a 0-100 health score."""

    @staticmethod
    def compute(health_data: dict) -> dict:
        scores = {}
        details = {}

        # 1. Issue response time (20%)
        issues = health_data.get("recentIssues", {}).get("nodes", [])
        response_times = []
        for issue in issues:
            comments = issue.get("comments", {}).get("nodes", [])
            if comments:
                created = datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))
                first_comment = datetime.fromisoformat(comments[0]["createdAt"].replace("Z", "+00:00"))
                delta_hours = (first_comment - created).total_seconds() / 3600
                response_times.append(delta_hours)

        if response_times:
            median_response = sorted(response_times)[len(response_times) // 2]
            if median_response < 4:
                scores["issue_response"] = 100
            elif median_response < 24:
                scores["issue_response"] = 80
            elif median_response < 72:
                scores["issue_response"] = 60
            elif median_response < 168:
                scores["issue_response"] = 40
            else:
                scores["issue_response"] = 20
            details["issue_response"] = f"{median_response:.0f}hr avg"
        else:
            scores["issue_response"] = 50
            details["issue_response"] = "no data"

        # 2. Issue close ratio (15%)
        closed = health_data.get("closedIssues90d", {}).get("totalCount", 0)
        total = health_data.get("totalIssues90d", {}).get("totalCount", 0)
        if total > 0:
            ratio = closed / total
            scores["issue_close_ratio"] = min(100, int(ratio * 120))
            details["issue_close_ratio"] = f"{ratio*100:.0f}%"
        else:
            scores["issue_close_ratio"] = 50
            details["issue_close_ratio"] = "no issues"

        # 3. Commit frequency (20%)
        commits = health_data.get("defaultBranchRef", {}).get("target", {}).get("history", {}).get("nodes", [])
        if commits:
            now = datetime.now(UTC)
            recent_commits = [
                c for c in commits
                if (now - datetime.fromisoformat(c["committedDate"].replace("Z", "+00:00"))).days <= 30
            ]
            commits_per_week = len(recent_commits) / 4.3
            if commits_per_week > 20:
                scores["commit_frequency"] = 100
            elif commits_per_week > 10:
                scores["commit_frequency"] = 80
            elif commits_per_week > 5:
                scores["commit_frequency"] = 60
            elif commits_per_week > 1:
                scores["commit_frequency"] = 40
            else:
                scores["commit_frequency"] = 20
            details["commit_frequency"] = f"{commits_per_week:.0f}/week"
        else:
            scores["commit_frequency"] = 20
            details["commit_frequency"] = "no commits"

        # 4. PR merge time (15%)
        prs = health_data.get("pullRequests", {}).get("nodes", [])
        merge_times = []
        for pr in prs:
            if pr.get("mergedAt"):
                created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
                merged = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
                days = (merged - created).total_seconds() / 86400
                merge_times.append(days)

        if merge_times:
            median_merge = sorted(merge_times)[len(merge_times) // 2]
            if median_merge < 1:
                scores["pr_merge_time"] = 100
            elif median_merge < 3:
                scores["pr_merge_time"] = 80
            elif median_merge < 7:
                scores["pr_merge_time"] = 60
            elif median_merge < 14:
                scores["pr_merge_time"] = 40
            else:
                scores["pr_merge_time"] = 20
            details["pr_merge_time"] = f"{median_merge:.0f} days"
        else:
            scores["pr_merge_time"] = 50
            details["pr_merge_time"] = "no PRs"

        # 5. Release cadence (15%)
        releases = health_data.get("releases", {}).get("nodes", [])
        if len(releases) >= 2:
            release_dates = [
                datetime.fromisoformat(r["publishedAt"].replace("Z", "+00:00"))
                for r in releases if r.get("publishedAt")
            ]
            if len(release_dates) >= 2:
                release_dates.sort(reverse=True)
                intervals = [
                    (release_dates[i] - release_dates[i + 1]).days
                    for i in range(len(release_dates) - 1)
                ]
                avg_interval = sum(intervals) / len(intervals)
                if avg_interval < 7:
                    scores["release_cadence"] = 100
                elif avg_interval < 14:
                    scores["release_cadence"] = 80
                elif avg_interval < 30:
                    scores["release_cadence"] = 60
                elif avg_interval < 90:
                    scores["release_cadence"] = 40
                else:
                    scores["release_cadence"] = 20
                details["release_cadence"] = f"every {avg_interval:.0f}d"
            else:
                scores["release_cadence"] = 30
                details["release_cadence"] = "rare"
        else:
            scores["release_cadence"] = 30
            details["release_cadence"] = "few releases"

        # 6. Contributor count (15%) — approximated from mentionableUsers
        contributors = health_data.get("mentionableUsers", {}).get("totalCount", 0)
        if contributors > 100:
            scores["contributors"] = 100
        elif contributors > 50:
            scores["contributors"] = 80
        elif contributors > 20:
            scores["contributors"] = 60
        elif contributors > 5:
            scores["contributors"] = 40
        else:
            scores["contributors"] = 20
        details["contributors"] = f"{contributors} total"

        # Weighted total
        weights = {
            "issue_response": 0.20,
            "issue_close_ratio": 0.15,
            "commit_frequency": 0.20,
            "pr_merge_time": 0.15,
            "release_cadence": 0.15,
            "contributors": 0.15,
        }

        total_score = sum(scores.get(k, 50) * w for k, w in weights.items())

        return {
            "overall": round(total_score),
            "scores": scores,
            "details": details,
        }


# Module-level singletons
growth_calculator = GrowthCalculator()
breakout_detector = BreakoutDetector()
health_scorer = HealthScorer()
