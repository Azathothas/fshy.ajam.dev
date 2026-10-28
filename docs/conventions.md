# Conventions

These rules bind every document, commit message, pull request and issue comment in this repository. They are
the working subset of ASD-STE100, Simplified Technical English, that the research repository also uses.

## 1. Words

1. **One word, one meaning, one part of speech.** "Record" is the JSON file. "Document" is a prose page.
   Do not use either for the other.
2. ⛔ **Never use a synonym to avoid repetition.** Repeat the term.
3. **Do not use a noun as a verb, or a verb as a noun.**
4. **Use the real verb, not a noun made from it.** "It fails", not "a failure occurs".
5. **No more than three nouns in a row.** Break a longer chain with a preposition.

## 2. Verbs and voice

6. **Active voice.** "The build writes the store", not "the store is written".
7. **Simple tenses.** Present for what is true, past for what happened.
8. **Do not drop the verb** in a sentence. A heading may drop it.
9. **Start an instruction with its verb.** "Run the build before you commit."

## 3. Sentences and paragraphs

10. **One instruction per sentence.**
11. **An instruction is at most 20 words. A description is at most 25.**
12. **A paragraph covers one topic, in at most six sentences.**
13. **Put the condition before the instruction.** "If the export finds a leak, read the first line."
14. **Put the warning before the step it applies to.**

## 4. Punctuation and characters

15. ⛔ **No dash between clauses.** A sentence that needs one is two sentences. No em dash, no en dash, and no
    `--` used as one.
16. **No slash that means "and or".** Write which one you mean.
17. **Nothing essential inside parentheses.**
18. ⛔ **ASCII only in documents, plus these five characters: `⛔` `⭐` `⚠` `✅` `❌`.** A specimen of another
    character may appear inside a code span or a code block.

## 5. Markers

| marker | meaning |
| --- | --- |
| `⛔` | a rule whose violation cannot be undone. A hard stop. |
| `⭐` | read or do this first. |
| `⚠` | a trap: it works until it does not, and the failure is quiet. |

They do not stack, and they stay rare: at most 30 per 100 lines.

## 6. Commits, pull requests and comments

- ⛔ **No tool or AI attribution.** No co-author trailer, no "generated with", no model or tool name.
- **The subject line says what the change does**, in at most 100 characters, and does not end with a full stop.
- **The body says why**, in the register above.
- ⛔ **No personal or operator detail** in a commit, a pull request or a comment. See [`../AGENTS.md`](../AGENTS.md).
