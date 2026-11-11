# First-time setup

About 20 minutes. You do three things: make a LinkedIn app, make a Notion key, and paste
three values into GitHub. Then you log in once.

You will paste secrets **only** into GitHub's secret boxes. Never into a chat, an issue or a file.

## What connects to what

```
Notion "Wednesday Posts"  --(Notion key)-->  GitHub robot  --(LinkedIn login)-->  your LinkedIn profile
        rows to post                         runs every 15 min                    the post appears here
```

- The **Notion key** lets the robot read the rows and set Status to Posted.
- The **LinkedIn app** is your own private "door" into LinkedIn. LinkedIn only lets apps post,
  so you need one. Nobody else uses it.
- The **LinkedIn login** is you pressing Allow once every 60 days, so the app may post as you.

## Part 1: the LinkedIn app

LinkedIn says every app must belong to a Company Page. The page is only a formality here.
Nothing is ever posted on it.

### 1a. A Company Page (skip if you already admin one, for example Humiwell's)

1. Open <https://www.linkedin.com/company/setup/new/>.
2. Choose **Company**.
3. Name: anything, for example `Sajjad Dhebar Projects`. LinkedIn fills in the web address for you.
4. Pick any Industry, Company size `0-1`, Company type `Self-employed`.
5. Tick the box that says you are allowed to act for this company. Click **Create page**.

### 1b. Create the app

1. Open <https://www.linkedin.com/developers/apps/new>. Sign in with your normal LinkedIn account.
   This also makes your developer account. There is no separate sign-up.
2. **App name**: `linkedin-poster`.
3. **LinkedIn Page**: type the name of your Company Page and pick it.
4. **Privacy policy URL**: leave empty.
5. **App logo**: upload any square picture (your photo is fine).
6. Tick the legal box. Click **Create app**.

### 1c. Verify the app with your page

1. In your new app, open the **Settings** tab.
2. Next to your page name, click **Verify**, then **Generate URL**.
3. Open that URL in a new tab and click **Verify**. (You are the page admin, so you approve yourself.)

### 1d. Add the two products

Open the **Products** tab. Click **Request access** on these two. Both are approved at once.

1. **Share on LinkedIn**. This allows posting (LinkedIn calls the permission `w_member_social`).
2. **Sign In with LinkedIn using OpenID Connect**. This tells the robot who you are, so it posts
   as you (`openid` and `profile`).

### 1e. Tell LinkedIn where to send you after login

1. Open the **Auth** tab.
2. Under **OAuth 2.0 settings**, next to *Authorized redirect URLs for your app*, click the pencil,
   then **Add redirect URL**.
3. Paste exactly this, with the `/` at the end:

   ```
   https://humiwell.github.io/linkedin-poster/
   ```

4. Click **Update**.
5. Lower on the same tab, under *OAuth 2.0 scopes*, you should now see `openid`, `profile` and
   `w_member_social`. If not, go back to 1d.

### 1f. Copy the two app values into GitHub

Stay on the **Auth** tab. At the top are **Client ID** and **Primary Client Secret**.

1. Open <https://github.com/humiwell/linkedin-poster/settings/secrets/actions/new>.
2. Name: `LINKEDIN_CLIENT_ID`. Secret: paste the Client ID. Click **Add secret**.
3. Open the same link again. Name: `LINKEDIN_CLIENT_SECRET`. Secret: paste the Primary Client Secret
   (click the eye to show it first). Click **Add secret**.

## Part 2: the Notion key

1. Open <https://www.notion.so/profile/integrations>.
2. Click **New integration**. Name: `linkedin-poster`. Workspace: the one with "Sajjad LinkedIn".
   Type: **Internal**. Click **Save**.
3. On the next screen, find **Internal Integration Secret**, click **Show**, then **Copy**.
4. Open <https://github.com/humiwell/linkedin-poster/settings/secrets/actions/new>.
   Name: `NOTION_TOKEN`. Secret: paste. Click **Add secret**.
5. Now let the key see the database. In Notion, open the **Sajjad LinkedIn** page. Click the `...`
   menu at the top right, then **Connections**, then pick `linkedin-poster` and confirm.
   (Notion's wording moves around. Look for "Connections" or "Add connections".)

The fourth secret, `TOKEN_KEY`, was already made for you when the repo was created.

## Part 3: log in to LinkedIn

1. Within 15 minutes of adding the secrets, the robot opens an issue called **Log in to LinkedIn**
   in the [Issues tab](https://github.com/humiwell/linkedin-poster/issues).
2. Click the link in it, press **Allow** on LinkedIn.
3. You come back to GitHub with a new issue already filled in. Press the green **Create** button.
4. About a minute later the robot answers "Logged in" and closes both issues.

## Part 4: test, then go live

1. **Safe check.** Actions tab, "Test post", *Run workflow*, step `check`. It posts nothing.
   Open the run and read the summary: it should say the login is OK, Notion is OK, list the next
   rows, and say the upload test is OK.
2. **Practice mode.** `config.yml` starts with `dry_run: true`. Each run only says what it would post.
3. **One real post.** When you are happy: Actions tab, "Test post", step `post`, type the row's
   exact Name and `POST`. That row is published for real and marked Posted.
4. **Go live.** In `config.yml`, change `dry_run: true` to `dry_run: false`.

Before going live, check Notion for rows that are Scheduled but were already posted by hand.
Set those to Posted. (Rows more than 6 hours late are skipped anyway, and an issue tells you.)
