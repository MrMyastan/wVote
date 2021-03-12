#!/usr/bin/env python3

import datetime
import uuid
import logging
import statistics
from typing import Optional
import pickle


current_week = None
next_week = None


def blank_week() -> dict:
    return {
        "theme": "Week XYZ: Fill this in by hand!",
        "date": "Month day'th 20XX",
        "submissionsOpen": True,
        "votingOpen": True,
        "entries": [],
        "votes": [],
        "voteParams": ["prompt", "score", "overall"]
    }


def get_week(get_next_week: bool) -> dict:
    """
    Returns a dictionary that encodes information for a week's challenge. If
    the requested week has no information, attempts to read previously
    serialized information. If the pickle object was not found, returns
    a new dictionary.

    Parameters
    ----------
    get_next_week : bool
        Whether the week that should be retrieved is the following week.
        False returns the current week's information, while True retrieves
        next week's information.

    Returns
    -------
    dict
        A dictionary that encodes information for a week. The information
        includes theme, date, whether submissions are open, and a list of
        entries.
    """
    global current_week, next_week

    if current_week is None:
        try:
            current_week = pickle.load(open("weeks/current-week.pickle", "rb"))
        except FileNotFoundError:
            current_week = blank_week()
            current_week["submissions_open"] = False
    if next_week is None:
        try:
            next_week = pickle.load(open("weeks/next-week.pickle", "rb"))
        except FileNotFoundError:
            next_week = blank_week()

    if get_next_week:
        return next_week
    else:
        return current_week


def save_weeks() -> None:
    """
    Saves `current_week` and `next_week` into pickle objects so that they can
    later be read again.
    """
    if current_week is not None and next_week is not None:
        pickle.dump(current_week, open("weeks/current-week.pickle", "wb"))
        pickle.dump(next_week, open("weeks/next-week.pickle", "wb"))
        logging.info("COMPO: current-week.pickle and next-week.pickle overwritten")


def move_to_next_week() -> None:
    """
    Replaces `current_week` with `next_week`, freeing up `next_week` to be
    replaced with new information.

    Calls `save_weeks()` to serialize the data after modification.
    """
    global current_week, next_week

    archive_filename = "weeks/archive/" + \
        datetime.datetime.now().strftime("%m-%d-%y") + ".pickle"
    pickle.dump(current_week, open(archive_filename, "wb"))

    current_week = next_week
    next_week = blank_week()

    save_weeks()


def create_blank_entry(entrant_name: str,
                       discord_id: int,
                       get_next_week: bool = True) -> str:
    """
    Create a blank entry for an entrant and returns a UUID

    Parameters
    ----------
    entrant_name : str
        The name of the entrant
    discord_id : int
        The entrant's Discord ID
    get_next_week : bool, optional
        Whether the entry should be for the folowing week, by default True

    Returns
    -------
    str
        A randomly generated UUID
    """
    entry = {
        "entryName": "",
        "entrantName": entrant_name,
        "discordID": discord_id,
        "uuid": str(uuid.uuid4())
    }
    get_week(get_next_week)["entries"].append(entry)

    return entry["uuid"]


def find_entry_by_uuid(uuid: str) -> Optional[dict]:
    for which_week in [True, False]:
        for entry in get_week(which_week)["entries"]:
            if entry["uuid"] == uuid:
                return entry
    return None


def entry_valid(entry: dict) -> bool:
    requirements = [
        "uuid",
        "pdf",
        "pdfFilename",
        "mp3",
        "mp3Format",
        "mp3Filename",
        "entryName",
        "entrantName",
    ]

    for requirement in requirements:
        if requirement not in entry:
            return False

    for param in ["mp3", "pdf"]:
        if entry[param] is None:
            return False

    return True


def count_valid_entries(week: dict) -> int:
    return len(e for e in week["entries"] if entry_valid(e))


def get_entry_file(uuid: str, filename: str) -> tuple:
    entry = find_entry_by_uuid(uuid)
    if entry is None:
        return None, None

    if "mp3Filename" in entry and entry["mp3Filename"] == filename:
        return entry["mp3"], "audio/mpeg"

    if "pdfFilename" in entry and entry["pdfFilename"] == filename:
        return entry["pdf"], "application/pdf"

    return None, None


def verify_votes(week: dict) -> None:

    if not "votes" in week:
        week["votes"] = []

    # Keeps track of set vs. unset votes, and makes sure a single user can
    # only vote on the same parameter for the same entry a single time
    userVotes = {}

    # Validate data, and throw away sus ratings
    for v in week["votes"]:
        for r in v["ratings"]:
            if not (v["userID"], r["entryUUID"], r["voteParam"]) in userVotes \
                    and r["rating"] <= 5 \
                    and r["rating"] >= 0:
                if r["rating"] == 0: # Unset rating
                    userVotes[(v["userID"], r["entryUUID"], r["voteParam"])] \
                        = False
                else:
                    userVotes[(v["userID"], r["entryUUID"], r["voteParam"])] \
                        = True
                # TODO: throw out ratings for made-up categories
                # (this will involve data-ifying the voteParams into the week)
            else:
                logging.warning("COMPO: FRAUD DETECTED (CHECK VOTES)")
                logging.warning("Sus rating: " + str(r))
                v["ratings"].remove(r)


def get_valid_scores(week: dict) -> dict:
    scores = {}

    for v in week["votes"]:
        valid_ratings = [r for r in v["ratings"] if r["rating"] != 0]

        if len(valid_ratings) == 0:
            # The user cleared all votes
            continue

        rating_values = [r["rating"] for r in valid_ratings]

        minimum = min(rating_values)
        maximum = max(rating_values)
        extent = maximum - minimum

        for r in valid_ratings:
            normalized = (float(r["rating"]) - (minimum - 1)) / (extent + 1) * 5

            scores.setdefault(r["entryUUID"], []).append((normalized, r["voteParam"]))

    return scores


def get_ranked_entrant_list(week: dict) -> list:
    """Bloc STAR Voting wooooo"""

    param_weights = {
        "prompt": 0.3,
        "score": 0.3,
        "overall": 0.4
    }

    if len(week["entries"]) < 1: # lol no one submitted
        return []

    verify_votes(week)

    scores = get_valid_scores(week)

    entry_pool = []
    ranked_entries = []

    # Write final scores to entry data, and put 'em all in entry_pool
    for e in week["entries"]:
        if entry_valid(e):
            e["voteScore"] = statistics.mean(score[0] for score in scores.get(e["uuid"], [(0, None)]))
            entry_pool.append(e)

    # Now that we have scores calculated, run the actual STAR algorithm
    while len(entry_pool) > 1:
        entry_pool = sorted(entry_pool, key=lambda e: e["voteScore"], reverse=True)

        entryA = entry_pool[0]
        entryB = entry_pool[1]

        preferEntryA = 0
        preferEntryB = 0

        for v in week["votes"]:
            # note that normalization doesn't matter for comparing preference
            scoreA = sum(r["rating"] * param_weights[r["voteParam"]] for r in v["ratings"] if r["entryUUID"] == entryA["uuid"])
            scoreB = sum(r["rating"] * param_weights[r["voteParam"]] for r in v["ratings"] if r["entryUUID"] == entryB["uuid"])

            if scoreA > scoreB:
                preferEntryA += 1
            elif scoreB > scoreA:
                preferEntryB += 1

        # greater than or equal to, as entryA is the entry with a higher score,
        # to settle things in the case of a tie
        if preferEntryA >= preferEntryB:
            ranked_entries.append(entry_pool.pop(0))
        else:
            ranked_entries.append(entry_pool.pop(1))

    # Add the one remaining entry
    ranked_entries.append(entry_pool.pop(0))

    for place, e in enumerate(ranked_entries):
        e["votePlacement"] = place + 1

    return list(reversed(ranked_entries))
