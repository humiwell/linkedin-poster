# LinkedIn auto-poster

This repo posts your LinkedIn posts for you. It reads the **Wednesday Posts** database in Notion
(inside the "Sajjad LinkedIn" page), and when a row's day and time arrive, it publishes that row
on your personal LinkedIn profile and marks the row as Posted. It runs for free on GitHub Actions.

First time here? Follow [SETUP.md](SETUP.md).

## How it works

1. **Every 15 minutes** the robot wakes up (Actions tab, "LinkedIn robot").
2. It reads every Notion row with Status **Scheduled**.
3. A row is due when its **Post date** has arrived and the UK time is 12:00 or later.
4. For a due row it takes:
   - the **caption**: the grey code block under the "Caption (copy into LinkedIn)" heading inside the row,
   - the **file** in the **Cover** column (optional).
5. It uploads the file to LinkedIn, waits until LinkedIn says it is ready, then publishes the post.
6. It sets the row's Status to **Posted** in Notion.
7. **Memory:** every post is written down in `state/state.json`, so running twice never posts twice.

GitHub sometimes starts runs a few minutes late, so a post can land up to about 20 minutes after 12:00.

### What you put in the Cover column

| Cover column | Post you get |
|---|---|
| Empty | Text only |
| One image (PNG, JPG, GIF) | Image post |
| Several images | Multi-image post (swipe through). Not tested live yet |
| One MP4 video | Video post |

## Your weekly job

Nothing, if the rows are ready. To hold a post back, change its Status away from Scheduled.
To let one go out, set Status to **Scheduled** and give it a **Post date**.

## Everyday controls (all in `config.yml`)

Open `config.yml` on GitHub, click the pencil, change a line, click *Commit changes*.
The next run uses it.

| I want to... | Change this |
|---|---|
| Pause posting | `paused: true` (back to `false` to restart) |
| Stop everything | Actions tab, "LinkedIn robot", `...` menu, *Disable workflow* |
| Practice without posting | `dry_run: true` |
| Change the posting time | `post_time: "08:30"` (UK time) |
| Give one row its own time | In Notion, turn on "Include time" on that row's Post date |
| Post to connections only | `visibility: CONNECTIONS` |
| Allow later catch-up | `max_late_hours: 24` |

In practice mode (`dry_run: true`) the robot posts nothing and changes nothing in Notion.
Open a run in the Actions tab to read what it would have posted.

## What each issue means

The robot talks to you through GitHub issues. Turn on notifications for this repo to get them by email
or in the GitHub phone app.

| Issue title | What happened | What you do |
|---|---|---|
| Setup is not finished | A secret is missing | Add it, see [SETUP.md](SETUP.md) |
| Log in to LinkedIn | There is no login yet | Click the link in the issue |
| LinkedIn login runs out on ... | 7 days or fewer left | Click the link in the issue. Posting still works until that date |
| LinkedIn login has run out | The 60 days are over | Click the link in the issue. Nothing posts until you do |
| LinkedIn login is not valid | LinkedIn cancelled the login (for example after a password change) | Click the link in the issue |
| Skipped ...: too late | A Scheduled row was more than 6 hours late | Already posted by hand? Set Status to Posted. Still want it? Give it a new Post date |
| Could not post ... | Failed 3 times | Read the error, fix the row in Notion. Any change to the row makes the robot try again |
| Check LinkedIn: ... may or may not have posted | The post was sent, but LinkedIn gave no clear answer | Look at your profile. The issue says what to do in each case |
| Cannot read Notion | The Notion key or the connection is wrong | See [SETUP.md](SETUP.md), part 2 |

## Log in again (every 60 days)

LinkedIn logins last about 60 days, and LinkedIn does not let a robot renew them. So:

1. Seven days before the end, the robot opens an issue with a login link.
2. Click the link and press **Allow** on LinkedIn.
3. You are sent back to GitHub with a new issue already filled in. Press the green **Create** button.

That is all. About a minute later the robot answers on the issue with the new end date.
It works on a phone. You must be signed in to GitHub as the owner of this repo.

How this stays safe:

- The login code in that issue works once, for 30 minutes, and only together with the app's secret,
  which only the robot has. After use the robot wipes it from the issue.
- Only issues created by the repo owner are accepted. Anyone else's are ignored.
- The login is saved in `state/token.enc`. That file is locked with the `TOKEN_KEY` secret, so it is
  useless without it, even though this repo is public.
- Once logged in, the robot refuses a login from a different LinkedIn account.

Never paste a token, key or secret into an issue, a file or a chat.

## One-off tests

Actions tab, "Test post", *Run workflow*:

- `check`: safe. Checks the login, reads Notion, lists the next rows, and uploads the next row's
  file to LinkedIn **without posting it**.
- `post`: publishes ONE row right now, whatever its date. Type the row's exact Name in `row`
  and `POST` in `confirm`. The row is marked Posted like any other.

## Files

| Path | What it is |
|---|---|
| `config.yml` | Your settings |
| `SETUP.md` | First-time setup, step by step |
| `state/state.json` | The robot's memory. Do not edit unless asked |
| `state/token.enc` | The locked LinkedIn login |
| `docs/index.html` | The small page LinkedIn sends you back to after login |
| `poster/` | The code |
| `tests/` | Practice runs against a pretend Notion and LinkedIn |
