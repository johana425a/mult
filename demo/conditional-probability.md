# Conditional probability and new information

This is a prepared example assisted by Codex for software demonstrations. It is not a textbook quotation, an official examination question, or a live classroom model response. It may be adapted for demonstrations.

## Learning goals

1. Explain which group is represented by the denominator of P(A|B).
2. Calculate conditional probabilities from a count table and distinguish P(A|B) from P(B|A).
3. Explain why new information changes the comparison group.

## Example

A community has 100 members. Forty know Python, thirty know photography, and eighteen know both.

| | Knows photography | Does not know photography | Total |
| --- | ---: | ---: | ---: |
| Knows Python | 18 | 22 | 40 |
| Does not know Python | 12 | 48 | 60 |
| Total | 30 | 70 | 100 |

For a randomly selected member, the probability of knowing Python is 40/100 = 0.4.

If the member is known to know photography, the relevant group contains thirty members. Eighteen of them know Python. Therefore P(Python|photography) = 18/30 = 0.6.

The definition is P(A|B) = P(A and B)/P(B), provided P(B) > 0.

If the condition is reversed, the relevant group contains forty members who know Python. Eighteen know photography, so P(photography|Python) = 18/40 = 0.45.

## Common misunderstanding

The numerators are the same, but the denominators represent different known conditions. The condition and conclusion cannot generally be exchanged. New information changes the comparison group; it does not change the members' skills.

## Check your understanding

1. Given that a randomly selected member does not know Python, what is the probability that the member knows photography? Explain why the denominator is sixty.
2. Explain why 18/100 is not the probability of knowing Python given knowledge of photography, and provide the correct calculation.

## Teacher reference

Do not reveal this section before the learner answers. The first result is 12/60 = 0.2. The second fraction, 18/100, is the joint probability of both skills; the requested conditional probability is 18/30 = 0.6.
