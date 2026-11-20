# Week 3 of the 30-Day AI Campaign Analyst Challenge

*Adding an AI analyst to an ad dashboard, without letting it make things up.*

By the end of week 2 my dashboard could show what happened to five ad campaigns on the iPinYou dataset: 53 million bids, 12 million impressions, one hour at a time. This week the brief was to make it **explain** what happened. A "What changed" tab, an insights panel, and a box where you can type a question and get an answer.

The hard part is not getting a language model to write a sentence about ad data. The hard part is making sure the sentence is true. A model will happily tell you that "CTR rose 18% on Tuesday" because that is what a sentence about CTR usually looks like. On a dashboard people use to move budget, a fluent wrong number is worse than no number.

So the rule for the week was simple: **the model never decides a number.**

## The pattern: query, generate, judge, show or withhold

Every AI feature I built this week goes through the same four steps, in one shared module so no step can be skipped:

1. **Query.** My code runs fixed SQL against the warehouse. All the maths (sums, ratios, percentage changes, rounding) happens in SQL, where it is exact.
2. **Generate.** Gemini gets only those query results and turns them into words, as JSON with fixed fields (a headline, one to three drivers, a confidence level). Its instructions say it may round a number or add a % sign, but never calculate a new one. If Gemini is busy, Groq writes instead.
3. **Judge.** A second model, Cohere, gets the same query results and the answer, and checks it claim by claim: does every number appear in the data? Is every "highest", "dropped" or "because" supported?
4. **Show or withhold.** A pass is stored and shown, with the SQL behind it. A fail goes back to the writer once, with the judge's reason. A second fail is withheld, and the dashboard says so instead of showing it.

Every call to every model is logged in a table: the prompt, the output, the verdict, the reason, the provider and how long it took.

Here is the very first test. Asked which advertiser had the most impressions, the writer said:

> Advertiser 1458 had the most impressions with 3,083,055.

The judge passed it: the advertiser and the number match the query. Then I handed the judge a planted lie, "Advertiser 1458 had 98,765,432 impressions, more than all others combined." It failed it, and its reason named both the wrong number and the unsupported comparison.


*Dashboard: dsp-campaign-analyst.vercel.app · Code: github.com/YOFTAHEGIZ/dsp-campaign-analyst*
