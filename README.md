# Personal SVSC Apple Calendar Feed

This repository creates a personal iCalendar (`svsc.ics`) feed from the public
Scotts Valley Sportsmen's Club calendar.

It does **not** require SVSC administrator access.

## What it does

1. Opens the public SVSC calendar list.
2. Finds the public Wild Apricot event pages.
3. Reads each event's actual date, start time, end time, and location.
4. Generates a standards-based `.ics` calendar.
5. Publishes it with GitHub Pages.
6. Rebuilds it automatically every 6 hours.

Each event uses the Wild Apricot event number as a stable iCalendar UID, so an
event should update in Apple Calendar rather than appearing as a new duplicate
when its time changes.

## GitHub setup

1. Create a new GitHub repository, for example `svsc-calendar`.
2. Upload all files in this project, including the `.github` folder.
3. Open the repository's **Settings → Pages**.
4. Under **Build and deployment → Source**, choose **GitHub Actions**.
5. Open **Actions → Refresh SVSC Calendar** and choose **Run workflow**.
6. When the run succeeds, GitHub Pages will show the site's URL.

Your Apple Calendar subscription URL will normally look like:

`https://YOUR-GITHUB-USERNAME.github.io/svsc-calendar/svsc.ics`

On a Mac, use **Calendar → File → New Calendar Subscription…** and paste that URL.

## Notes

- The source site remains the authority. This project only reads public event data.
- GitHub scheduled workflows can occasionally run late.
- GitHub says scheduled workflows in a public repository can be disabled after
  60 days without repository activity. If that becomes an issue, the same
  converter can be moved to Cloudflare Workers or another always-on service.
