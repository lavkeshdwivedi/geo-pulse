# Keeping the repo lean

GeoPulse runs every hour and publishes a static site. That is a recipe for a repository that quietly grows without limit, and this one did. This page explains what went wrong, how it was fixed, and the rules to follow if you fork the template or build something similar.

## What happened

Until October 2026 the workflow committed the whole generated `site/` folder back to `main` on every run. Two details made that expensive:

1. Every run rebuilt every archived edition page, not just the new one.
2. Each page carried a "generated at" timestamp, so every rebuilt page was a changed file.

So one hourly run committed roughly 4,300 modified HTML files. Git stores a new copy of each changed file, and after about 2,100 runs GitHub reported the repository at around 15 GB. A fresh `git clone` took hours, `git fetch` on an old checkout stalled while downloading a 10 GB pack, and failed fetches left gigabytes of temporary pack files behind on disk.

None of that HTML needed to be in git. The workflow already deploys `site/` to GitHub Pages as a build artifact, so the committed copy was never what visitors saw.

## The fix

1. **Generated files are not committed.** The generated parts of `site/` are listed in `.gitignore`. The workflow rebuilds them on every run from source data and uploads them with `actions/upload-pages-artifact`.
2. **Only source data is committed.** That is `newsletter.json`, `newsletter.md`, `newsletter.hi.md`, the markdown archive in `newsletters/`, and the README status block. These are small, and an archived edition never changes after it is written.
3. **History was rewritten once** with `git filter-repo` to remove the generated HTML from every past commit, then force-pushed. This is a one-time step. You only need it if your fork already grew.

## Rules for forks and similar projects

- **Never commit build output from a scheduled workflow.** If a file can be regenerated from other files in the repo, deploy it as an artifact instead of committing it.
- **Keep timestamps out of files you do commit** unless the timestamp is the point. A timestamp in a template turns every regeneration into a full rewrite.
- **Append, don't rewrite.** Archives should be write-once files. A run should add one file, not touch a thousand.
- **Watch the size.** `gh api repos/OWNER/REPO --jq .size` returns the size in KB. If it climbs every day, something is committing generated output.
- **Use a shallow or partial clone** for local work on any repo with a bot committing to it: `git clone --filter=blob:none`.

## If your fork already bloated

1. Pause the workflow: `gh workflow disable newsletter.yml`.
2. Pull the latest template changes so your workflow and `.gitignore` match this repo, and commit them.
3. Clone your fork into a scratch folder and strip the generated paths from history:

   ```bash
   pip install git-filter-repo
   git filter-repo --invert-paths \
     --path site/index.html --path site/feed.xml --path site/newsletter.json \
     --path site/.nojekyll --path site/newsletters/ --path site/hi/ \
     --path site/archive/ --path site/about/ --path site/terms/ --path site/privacy/
   ```

4. Push the result: `git push --force-with-lease origin main`, plus any other branches you rewrote.
5. Re-enable the workflow and run it once by hand to confirm the site still deploys.
6. Re-clone locally. Old clones still hold the old history.

GitHub recalculates the reported size after its own garbage collection, which can take a while. If it doesn't drop, GitHub Support can run it for you.
