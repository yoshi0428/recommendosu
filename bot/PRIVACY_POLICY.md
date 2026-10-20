# recommendosu Discord bot: Privacy Policy

Effective: October 19, 2026

This policy covers the recommendosu Discord bot (the "bot"), run by yoshi0428. It explains what the bot stores when you use it, why, for how long, and how to have it removed. It does not cover the recommendosu.com website.

## What the bot stores

| What | When | Where | How long |
|---|---|---|---|
| Your Discord user ID, the osu! player ID and username you linked, and when you linked it | You run `/link` | The bot's link database | Until you run `/unlink` (running `/link` again replaces it) |
| Your Discord user ID and the ID of your latest `/rec` result | You run `/rec` | The bot's memory | Until you run `/unlink`, run `/rec` again, or the bot restarts |
| Your `/rec` result (the list of recommended maps), labelled with your Discord user ID | You run `/rec` | The recommender server's memory | 30 minutes after you last use it, or until your next `/rec` |
| The osu! player's public top and recent scores | `/rec` runs for that player | The recommender database | Kept, and refreshed on later requests (see "osu! scores" below) |
| Server logs, which can include osu! usernames and player IDs looked up through `/link` and `/rec` | Any command | Log files on the server | Until overwritten as the logs rotate (oldest entries go first) |

### osu! scores

To recommend maps, the bot fetches a player's top and recent scores from the osu! API. These are public on osu! already. They are stored so they don't need to be fetched again for every request, and the same data is used by the recommendosu.com website. They are tied to the osu! player ID, not to anyone's Discord account.

## What the bot doesn't collect

- The content of your messages. The bot only sees the commands you send it.
- Server member lists, presence or activity.
- Your email, IP address or any payment information.

## How the data is used

Only to run the commands you use: remembering your linked account for `/rec`, paging through your results, and letting `/classify index` find a map from your last `/rec`. Logs are used to fix problems.

The data is not sold, not used for advertising, and not used for analytics or tracking.

## Who else receives data

- **osu! (ppy Pty Ltd):** osu! usernames and player IDs are sent to the osu! API to look up players and their scores. See the [osu! privacy policy](https://osu.ppy.sh/legal/en/Privacy).
- **Discord:** handles every command and reply. See [Discord's privacy policy](https://discord.com/privacy).

No one else receives data from the bot. In particular, nothing is sent to AI or analytics services: recommendations and classifications are computed on the bot's own server.

## Who can see your results

`/rec` replies are posted in the channel, so anyone who can read the channel sees the recommendations and the osu! username they're for. This includes `/rec` messages such as a player not being found or no maps matching. Replies to `/classify`, `/link`, `/unlink` and `/help`, and messages about mistakes in a command's options, are only visible to you.

## Removing your data

- **Run `/unlink`.** It deletes your linked account from the bot and forgets your latest `/rec`. Your cached `/rec` result can no longer be reached and is deleted within 30 minutes.
- **Ask for anything else to be removed**, such as log entries or the stored scores for your osu! account, using the contacts below. Stored scores will be fetched again if someone later runs `/rec` for that account.

## Children

The bot follows Discord's minimum age requirements and is not directed at children under 13.

## Changes to this policy

Changes are made in this file, with the date above updated. Earlier versions are in the repository's history.

## Contact

- The recommendosu Discord server: https://discord.gg/Dh4TzKGGB7
- GitHub issues: https://github.com/yoshi0428/recommendosu/issues
- Discord DMs at yoshiekn
- osu!pm at yoshi0428