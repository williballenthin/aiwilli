GitHub Activity Integration Research

Date: 2026-03-11

1. Goal

We want Weave to pull a day-by-day record of GitHub work into the vault and daily note system.
The target activity set is:
- commits
- pull requests opened
- issues opened
- comments on issues and pull requests
- pull request reviews and review comments
- commit comments

The main question is whether GitHub GraphQL can start from a user account and efficiently enumerate this activity by day.

2. Short answer

GraphQL can cover a large part of this from `user(login: ...)`, but not all of it cleanly.

What GraphQL does well:
- authored issues by date range
- authored pull requests by date range
- pull request reviews by date range
- top-level issue / PR conversation comments via `issueComments`
- commit comments via `commitComments`
- contribution counts by repository and day via `contributionsCollection`

What GraphQL does not give cleanly from the user node:
- a single complete per-user activity feed
- individual commit links from contribution data
- a global user-level connection for pull request review comments
- a good incremental cursor for commit comments

Conclusion: GraphQL should be part of the design, but it should not be the only source if we want a reliable daily work log.

3. Most useful GraphQL surfaces

3.1 `User.contributionsCollection(from:, to:)`

Verified against the live schema on 2026-03-11.

This is the best GraphQL entry point for day-windowed authored work.
It supports:
- `issueContributions`
- `pullRequestContributions`
- `pullRequestReviewContributions`
- `commitContributionsByRepository`
- totals for each contribution family
- `organizationID` filtering if we later want a work-only view for one org

This is strong for backfill and reconciliation because it already accepts a date range.

Important limitation: commit contributions are aggregated, not individual commits.
The contribution node has:
- `occurredAt`
- `commitCount`
- `repository`
- `url`

It does not provide commit SHAs or commit URLs.
In live queries, commit `occurredAt` values appeared as day-bucket timestamps rather than real commit timestamps. For example, commit contribution timestamps came back as `07:00:00Z` or `08:00:00Z` for entire days, while issue / PR / review contributions had exact timestamps.

Implication: `contributionsCollection` is good for knowing that commit activity happened in a repo on a day, but not for producing a complete list of commit links.

3.2 `User.issueComments`

Verified against the live schema on 2026-03-11.

This returns exact comment objects with:
- `createdAt`
- `updatedAt`
- `url`
- `repository`
- `issue`

This is useful because it includes comments on pull request conversation threads too, since pull requests are also issues. In live queries, comments on PRs appeared here.

Limitations:
- there is no server-side date filter
- the only documented ordering field is `UPDATED_AT`

Implication: incremental sync is possible, but we must store comment IDs and filter by `createdAt` client-side. Edited old comments can resurface because ordering is by update time.

3.3 `User.commitComments`

Verified against the live schema on 2026-03-11.

This returns exact commit comment objects with:
- `createdAt`
- `updatedAt`
- `url`
- `repository`
- `commit`

Limitations:
- no documented `orderBy`
- no server-side date filter

Empirically, `first:` returned oldest comments and `last:` returned newest comments, but the lack of an explicit ordering contract makes this weaker than `issueComments` for synchronization.

3.4 `User.pullRequests` and `User.issues`

These can enumerate authored PRs and issues directly from the user node.

Useful properties:
- `pullRequests` supports `orderBy`
- `issues` supports `orderBy` and `filterBy`

However, for daily indexing, `contributionsCollection` is a better primary source because it already groups authored PRs and issues into a bounded date window.

3.5 Pull request reviews versus review comments

`contributionsCollection.pullRequestReviewContributions` gives review submissions with exact timestamps and links.
This is good for activities like:
- approved PR
- commented review
- changes requested

But GraphQL does not expose a global user-level `pullRequestReviewComments` connection from `User`.
The live schema on 2026-03-11 had no such field.

If we want inline review comments in GraphQL, the practical route is:
1. get review submissions from `pullRequestReviewContributions`
2. expand each `pullRequestReview` via its `comments` connection

This works for review comments attached to a review, but it is not a user-wide one-shot query.

3.6 GraphQL search is not enough for commits

The live GraphQL schema on 2026-03-11 exposed `search(query:, type:)`, but `SearchType` only included:
- `ISSUE`
- `ISSUE_ADVANCED`
- `REPOSITORY`
- `USER`
- `DISCUSSION`

Notably, it did not include commit search.

Implication: GraphQL search cannot be the commit-discovery path.

4. Most useful REST surfaces

4.1 `/users/{username}/events`

This is the closest thing GitHub has to a user activity feed.

Official behavior:
- if authenticated as the given user, private events are included
- the API is not real-time; GitHub documents latency of roughly 30 seconds to 6 hours
- the endpoint is optimized for polling with `ETag` and `X-Poll-Interval`
- the timeline includes up to 300 events
- only events from the past 30 days are included

This endpoint is the best source for recent incremental sync because it contains exact activity events with timestamps and payloads.

Relevant event types observed in a live query on 2026-03-11:
- `PushEvent`
- `PullRequestEvent`
- `IssueCommentEvent`
- `PullRequestReviewEvent`
- `PullRequestReviewCommentEvent`
- `CreateEvent`

This is already enough to cover most day-to-day work.

Important detail: in a live `PushEvent`, GitHub returned `before`, `head`, and `ref`, but not the expanded commit list.
That is still usable because it gives a precise push boundary that can be expanded with the compare API.

4.2 Compare API for push expansion

REST has `GET /repos/{owner}/{repo}/compare/{basehead}`.
This can expand a `PushEvent` into the actual commits between `before` and `head`.

Implication: the practical path for commit links is often:
- poll user events
- find `PushEvent`
- call compare on `before...head`
- emit commit URLs from the compare result

This is much better than relying on contribution counts when we want actual commit links.

4.3 Search API

Search is useful as a fallback and repair tool, not as the primary sync feed.

`/search/issues` supports qualifiers that are directly relevant here:
- `author:`
- `commenter:`
- `involves:`
- `reviewed-by:`
- `created:`
- `updated:`
- `is:issue`
- `is:pr`

Examples of what this can find:
- PRs opened by a user on a day
- issues opened by a user on a day
- issues / PRs a user commented on
- PRs reviewed by a user

Important limitations from the official docs:
- up to 1,000 results per search
- up to 4,000 repositories searched for a query
- `incomplete_results` can be `true` on timeouts

`/search/commits` supports:
- `author:` / `committer:`
- `author-date:` / `committer-date:`

Important limitation: commit search only searches the default branch.
That makes it a poor primary source for development work done on feature branches before merge.

4.4 Per-resource expansion endpoints

Once search or events identify a candidate issue / PR / review, REST provides per-resource expansion such as:
- issue timeline: `GET /repos/{owner}/{repo}/issues/{issue_number}/timeline`
- issue events: `GET /repos/{owner}/{repo}/issues/{issue_number}/events`
- PR reviews: `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews`
- repository-wide PR review comments: `GET /repos/{owner}/{repo}/pulls/comments`

These are useful when we need to reconcile exact activity details, but they are not user-centric entry points.
They are the second hop after we already know which issue / PR to inspect.

5. What this means for a Weave sync design

5.1 Best recent-sync path

For the last 30 days, the best primary source is the REST user events feed.
Reasons:
- user-centric
- exact timestamps
- exact event types
- exact resource URLs for comments and reviews
- covers private activity when authenticated as the same user
- supports efficient polling with `ETag`

This is the cleanest answer to the "start at my user account and spider out" requirement.

5.2 Best backfill / reconciliation path

For durable history and repair, use GraphQL from the user node.
Recommended queries:
- `contributionsCollection(from:, to:)` for authored issues, PRs, review submissions, and commit activity counts
- `issueComments` for exact top-level issue / PR comments
- `commitComments` for exact commit comments
- optional expansion of `pullRequestReview.comments` for inline review comments once review submissions are known

This gives historical coverage beyond the 30-day events window.

5.3 Commit strategy

Commits are the hardest part.

No single API gives a complete user-centric, long-range list of individual commit links across all repositories and branches.

The practical options are:
- recent commits: derive from `PushEvent` + compare API
- commits associated with authored PRs: expand PR commits from authored PRs if we want PR-centric work summaries
- historical aggregate fallback: use GraphQL commit contribution counts when exact commit URLs are unavailable
- search fallback: use `/search/commits` only when default-branch coverage is acceptable

If exact commit URLs are a hard requirement for all historical activity, we should expect a more expensive repo-by-repo crawl.

5.4 Recommended data model

Normalize all harvested activity into one local table or JSON record format with fields like:
- stable source ID
- activity kind (`commit`, `pr_opened`, `issue_opened`, `issue_comment`, `pr_review`, `pr_review_comment`, `commit_comment`, `push`)
- `occurred_at`
- local day key
- repo name
- primary URL
- parent URL if applicable
- title / subject if available
- raw payload reference
- source API (`events`, `graphql`, `search`, `resource_expand`)

Then daily-note generation becomes a pure rendering step from normalized activity records.

5.5 Suggested synchronization shape

A reasonable design is:
- frequent incremental sync from `/users/{username}/events` using `ETag`
- store raw events and normalized items separately
- nightly reconciliation for recent days with GraphQL
- occasional explicit backfill for older ranges with GraphQL day windows
- use Search API only for repair or one-off discovery

This splits the problem into:
- recent, exact, efficient feed ingestion
- slower historical reconciliation

6. Recommended implementation direction

Recommendation:
- primary source for recent work: REST user events feed
- primary source for historical authored work: GraphQL `contributionsCollection`
- primary source for top-level issue / PR comments: GraphQL `issueComments`
- primary source for review submissions: GraphQL `pullRequestReviewContributions`
- primary source for exact recent commit links: `PushEvent` expanded through compare API
- fallback source for missed history: Search API plus per-resource expansion

This is better than a GraphQL-only design because GraphQL alone does not provide a complete per-user activity feed with individual commit and review-comment coverage.

7. Open design questions

- Do we need exact commit URLs for every historical commit, or is a repo/day commit summary acceptable when older activity cannot be reconstructed cheaply?
- Should Weave index all GitHub activity, or only activity in selected owners / orgs / repositories?
- Should force-pushes and branch creation events be included in daily notes, or treated as implementation detail?
- Should review comments be rendered individually, or rolled up into their parent review / PR?
- What local timezone should define the daily-note boundary?

8. Sources

Official docs:
- GitHub REST activity events: https://docs.github.com/rest/activity/events
- GitHub REST search: https://docs.github.com/rest/search/search
- GitHub issue / PR search qualifiers: https://docs.github.com/search-github/searching-on-github/searching-issues-and-pull-requests
- GitHub commit search qualifiers: https://docs.github.com/search-github/searching-on-github/searching-commits
- GitHub compare two commits: https://docs.github.com/rest/commits/commits#compare-two-commits
- GitHub issue timeline endpoint: https://docs.github.com/rest/issues/timeline#list-timeline-events-for-an-issue
- GitHub PR reviews endpoint: https://docs.github.com/rest/pulls/reviews#list-reviews-for-a-pull-request
- GitHub repository PR review comments endpoint: https://docs.github.com/rest/pulls/comments#list-review-comments-in-a-repository

Live schema / API verification on 2026-03-11 using `gh api graphql` and `gh api`:
- `User.contributionsCollection(from:, to:)`
- `User.issueComments`
- `User.commitComments`
- `User.pullRequests`
- `User.issues`
- `Query.search`
- `SearchType`
- `/users/{username}/events`

Relevant live observations from those checks:
- GraphQL has no user-level `pullRequestReviewComments` connection
- GraphQL search does not include commit search
- `contributionsCollection` commit data is aggregated by repo/day, not individual commits
- `issueComments` includes comments on PR conversation threads
- `PushEvent` exposes `before` and `head`, which can be expanded via compare
