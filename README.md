# FanzaDL WebUI

A web interface for browsing your FANZA purchased video library and downloading content.

## Features

- Browse your full FANZA library with cover art and purchase details
- Select stream quality (resolution, bitrate, codec) per video or per part
- Track download progress in real time
- Support for multi-part videos with independent part selection
- Copy stream URLs for use in external players/downloaders

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

Open [http://localhost:4352](http://localhost:4352) in your browser.

## Usage

**First login**

The first time you access the UI, you will be prompted to enter your FANZA email and password. This information is only used to generate authentication tokens, and then discarded. It is never stored or transmitted. You can log out and log in with a different account at any time.

**Library**

The homepage shows all videos in your FANZA library. Click a video card to open the download dialog, where you can choose the download quality before starting the download.

**Downloads**

The **Downloads** page lists all active and completed download jobs with real-time progress, speed, and segment counts. You can stop an active download at any time.

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
