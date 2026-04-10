# GeoPulse

GeoPulse is an automatic geopolitics newsletter, delivering curated global affairs updates and smart summaries directly to your GitHub Pages site. Fresh insights, every hour.

## Features

- Hourly (configurable) geopolitics news update
- Smart summaries using language models
- Completely automated using GitHub Actions
- Beautiful static dashboard via GitHub Pages

## How it works

This project uses GitHub Actions to fetch the latest news about geopolitics, generates a summarized newsletter (`newsletter.md`), and publishes it on a static website using GitHub Pages. Updates can be configured to run every hour or at your preferred schedule.

## Configuration

- To change the update frequency, edit the workflow schedule in `.github/workflows/newsletter.yml`.