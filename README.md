# FanzaDL WebUI

A web interface for browsing your FANZA video library and downloading content.

## Features

- Browse your full FANZA library with cover art and video details
- Download all parts of a video in one click, with support for multiple quality options
- Parallel downloads with real-time progress tracking and speed monitoring
- Configurable output filename templates
- Automatic library updates - new videos added to your library will automatically get downloaded
- Generate video stream URLs for use in external players/downloaders

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)

## Quick Start

1. Copy the `.env.example` and `docker-compose.yml` files at the root of this repository. Rename the copied `.env.example` to `.env`.

2. Edit the `.env` file and set `DOWNLOAD_DIR` to a path to an **existing directory** in your computer

```env
DOWNLOAD_DIR=<your path>
```

3. Set a `TOKEN_ENCRYPTION_KEY` in your `.env` file. This can be any secret string (e.g. a random password). Without it, you will need to log in again every time the container restarts.

```env
TOKEN_ENCRYPTION_KEY=<any secret string>
```

4. Start the container:

```sh
docker compose up -d
```


## Configuration

The following environment variables can be set in your `.env` file:

| Variable | Required | Default | Description |
|---|---|---|---|
| `DOWNLOAD_DIR` | Yes | — | Path to the download output directory on your machine |
| `TOKEN_ENCRYPTION_KEY` | Recommended | — | Any secret string; enables session persistence across container restarts |
| `DEFAULT_LOG_LEVEL` | No | `INFO` | Initial logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Accessing the UI

Open [http://localhost:4352](http://localhost:4352) in your browser. The first time you launch the app, it will automatically generate a temporary password for you to log in with. You can find this password in the container logs:

```sh
WARNING: App password generated: <password>
```

You can change this password after logging in from the **Settings** page.

## Usage

**Library**

The homepage shows all videos in your FANZA library. Click a video card to open the download dialog, where you can choose the download quality and preview the output path before starting the download.

**Downloads**

The **Downloads** page lists all active and completed download jobs with real-time progress, speed, and segment counts. You can stop an active download at any time.

**History**

The **History** page shows a log of all past download attempts, including successes and failures, with timestamps and error messages if applicable.

**Settings**

The **Settings** page lets you tune download parallelism, customize output filename templates, schedule automatic library refreshes with optional auto-download behavior, and adjust log verbosity.

## Where are my downloads?

Downloaded files are saved to the whatever directory you set in **Step 2** of the quickstart. 

## Updating

```sh
docker compose pull
docker compose up -d
```

## Stopping

```sh
docker compose down
```
