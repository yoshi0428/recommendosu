# recommendosu Discord bot: Privacy Policy

Effective: October 19, 2026

This policy covers the recommendosu Discord bot (the "bot"), which yoshi0428 runs. It tells what the bot stores about your use, why, for how long, and how to have it removed. It does not cover the recommendosu.com website.

## What the bot stores

| What | When | Where | How long |
|---|---|---|---|
| Your Discord user ID, the osu! player ID and username that you linked, and the time of the link | You run `/link` | The link database of the bot | Until you run `/unlink` (a new `/link` replaces it) |
| Your Discord user ID and the ID of your latest `/rec` result | You run `/rec` | The memory of the bot | Until you run `/unlink`, you run `/rec` again, or the bot restarts |
| Your `/rec` result (the list of recommended maps), labeled with your Discord user ID | You run `/rec` | The memory of the recommender server | 30 minutes after your last use of it, or until your next `/rec` |
| The public top and recent scores of the osu! player | `/rec` runs for that player | The recommender database | Kept, and refreshed on later requests (see "osu! scores" below) |
| Server logs. They can include the osu! usernames and player IDs that `/link` and `/rec` look up | Any command | Log files on the server | Until the log rotation overwrites them (the oldest entries go first) |

### osu! scores

To recommend maps, the bot fetches the top and recent scores of a player from the osu! API. These scores are already public on osu!. The bot stores them, so that it does not fetch them again for each request. The recommendosu.com website uses the same data. The scores are tied to the osu! player ID, not to a Discord account.

## What the bot does not collect

- The content of your messages. The bot sees only the commands that you send to it.
- Server member lists, presence or activity.
- Your email, your IP address or any payment information.

## How the data is used

The data is used only to run the commands that you use: to remember your linked account for `/rec`, to page through your results, and to let `/classify index` find a map from your last `/rec`. The logs are used to fix problems.

The data is not sold. It is not used for advertising, analytics or tracking.

## Who else receives data

- osu! (ppy Pty Ltd): the bot sends osu! usernames and player IDs to the osu! API to find players and their scores. See the [osu! privacy policy](https://osu.ppy.sh/legal/en/Privacy).
- Discord: Discord handles each command and reply. See the [Discord privacy policy](https://discord.com/privacy).

No one else receives data from the bot. In particular, the bot sends nothing to AI or analytics services. The recommendations and the classifications are calculated on the server of the bot.

## Who can see your results

The bot posts `/rec` replies in the channel. Thus anyone who can read the channel sees the recommendations and the osu! username that they are for. This includes `/rec` messages that tell, for example, that a player was not found or that no maps matched. Only you can see the replies to `/classify`, `/link`, `/unlink` and `/help`. Only you can also see the messages about mistakes in the options of a command.

## Removing your data

- Run `/unlink`. It deletes your linked account from the bot and forgets your latest `/rec`. After that, nothing can get to your cached `/rec` result, and it is deleted within 30 minutes.
- To have anything else removed, use the contacts below. For example, log entries or the stored scores of your osu! account. If someone later runs `/rec` for that account, the bot fetches its scores again.

## Children

The bot follows the minimum age requirements of Discord, and it is not for children under 13.

## Changes to this policy

Changes are made in this file, and the date above is updated. The earlier versions are in the history of the repository.

## Contact

- The recommendosu Discord server: https://discord.gg/Dh4TzKGGB7
- GitHub issues: https://github.com/yoshi0428/recommendosu/issues
- Discord DMs at yoshiekn
- osu!pm at yoshi0428
