---

## How it works

1. Every Monday a GitHub Action searches GitHub for repos created in the last $new_window_days days, and for repos up to $traction_months months old with at least $traction_min_stars stars.
2. Each repo is placed by the location on its owner's GitHub profile: SF Bay Area, Rest of US, Outside US, or Location unknown.
3. Free rules drop forks, archived repos, mirrors, templates, profile repos, GitHub Pages sites and likely star farms.
4. Claude reads each remaining repo's description and README. It keeps real tools, libraries, apps and research, and drops tutorials, link lists, demos and spam. Reviews run overnight, up to $max_reviews a night.
5. Star counts are recorded every week. Repos stop being tracked when they turn $traction_months months old and stay in the monthly lists.

**Notes**

- The "What it solves" lines are written by AI and may be imperfect.
- Locations are shown as their owners wrote them on GitHub.
- Want a repo added or removed? [Open an issue](https://github.com/$repo/issues/new).
