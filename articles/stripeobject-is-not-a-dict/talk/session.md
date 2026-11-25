# Talk: My first paying customer stayed on Free

For Sessionize (speaker profile > Sessions) and Speaker Deck (deck description).

**Title:** My First Paying Customer Stayed on the Free Plan: a Stripe Webhook Post-Mortem

**Short description (Speaker Deck):**
stripe-python 15 stopped making StripeObject a dict. My tests used dicts and passed; the first real checkout crashed
with one word: get. What happened, why the error was one word, the fix, and how I build Stripe webhooks now.
Code: https://github.com/LuisEduardoGE/fastapi-stripe-webhooks

**Abstract (Sessionize):**
The first real customer of a subscription product paid for Pro, Stripe took the money, and our database kept them on
Free. The only clue was an admin alert that said "Error: get". The webhook handler had passed every test, because the
tests built events from plain dicts, and stripe-python 15 had quietly stopped making StripeObject a dict.

This talk walks through the incident with the real code: why the error message was a single word, a second trap
hidden in the same file (getattr on a dict that silently returns the default), the fix of normalizing once at the
webhook edge, and the test that would have caught it, built from a real stripe.Event. It ends with how the customer
was repaired and six rules for Stripe webhooks: normalize at the edge, test with the real class, verify the raw body,
store before you acknowledge, answer fast and work later, and log the exception type.

You leave with a pattern you can apply to any SDK object that looks like a dict but isn't, and a public demo repo
(FastAPI, 25 tests, no Stripe keys needed).

**Format:** Session, 25-30 minutes · **Level:** Intermediate · **Language:** English (also French or Portuguese)
**Tags:** Python, FastAPI, Stripe, Testing, Payments
**Slides:** talk/slides.pdf (14 slides, 16:9)
