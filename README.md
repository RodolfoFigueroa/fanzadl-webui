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

1. Copy the `.env` and `docker-compose.yml` files at the root of this repository.

2. Edit the `.env` file and fill in your FANZA credentials:

```env
FANZA_EMAIL=your@email.com
FANZA_PASSWORD=yourpassword
```

3. Edit the `docker-compose.yml` file and in the `volumes:` section replace `<YOUR_DOWNLOAD_DIR>` with a path to an **existing directory** in your computer:

```yml
volumes:
  - <YOUR_DOWNLOAD_DIR>:/download
  - image_cache:/image_cache
```

4. Start the container:

```sh
docker compose up -d
```


## Accessing the UI

Open [http://localhost:4352](http://localhost:4352) in your browser.

## Usage

**Library**

The homepage shows all videos in your FANZA library. Click a video card to open the download dialog, where you can choose the stream quality and filename for each part before starting the download.

**Downloads**

The **Downloads** page lists all active and completed download jobs with real-time progress, speed, and segment counts. You can stop an active download at any time.

**Settings**

The **Settings** page lets you configure the number of download threads (1-32). This setting is saved in your browser. It is not recommended to go above **4** threads, otherwise FANZA's systems will rate limit you.

## Where are my downloads?

Downloaded files are saved to the whatever directory you set in **Step 3** of the quickstart. 

## Updating

```sh
docker compose pull
docker compose up -d
```

## Stopping

```sh
docker compose down
```
