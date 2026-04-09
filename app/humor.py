from __future__ import annotations

from random import choice


def pick_line(mode: str) -> str:
    if mode == "off":
        return "Leaderboard calibrated. Drama pending."
    if mode == "dry":
        lines = [
            "Math is sober. Golf remains chaotic.",
            "The cut line is less forgiving than your group chat.",
            "Another day, another perfectly normal quadruple.",
            "The model says edge. The putter says no.",
            "Three feet for par, three years off your life.",
            "Expected score: -2. Actual score: emotional damage.",
            "Data confirms the ball prefers water features.",
            "Fairways hit are temporary. Doubles are forever.",
            "Every pick looked elite on Wednesday night.",
            "The spreadsheet is calm. Your roster is not.",
            "Tempo looked great until the first tee box.",
            "The leaderboard moved. Your confidence did not.",
        ]
        return choice(lines)
    lines = [
        "Somewhere, a 3-footer just got called a traitor.",
        "Tiger-era optimism, modern-era lower-back lawsuit.",
        "Your lock pick is sweating like a sinner in Amen Corner.",
        "A tradition unlike any other: panic-texting by hole 6.",
        "That drive was long, hard, and still somehow disappointing.",
        "He striped it down the middle and still fucked it up from 90.",
        "Nothing says romance like a lip-out for double.",
        "Your roster is one bad wedge away from a public meltdown.",
        "Today’s strategy: bomb it, pray, and blame the greens.",
        "Three putts and a tequila sounds like course management.",
        "He found the rough so often it has his mailing address.",
        "That bunker shot had all the finesse of a bar fight.",
        "Your birdie streak died faster than your confidence.",
        "The putter is cold, the language is hot, and the card is filthy.",
        "Bold move laying up with absolutely zero self-respect.",
        "He attacked the pin like a hero and scored like a villain.",
        "That tee shot started online and finished in another zip code.",
        "He flirted with eagle and went home with bogey.",
        "If golf is foreplay, your picks skipped straight to heartbreak.",
        "These greens are slicker than your cousin after two IPAs.",
        "Congratulations, that approach just invented new profanity.",
        "Every time you say 'safe play,' a caddie rolls their eyes.",
        "Round management by vibes and questionable life choices.",
        "He drained that putt like rent was due.",
        "The card is so dirty it needs parental controls.",
        "Front nine: confidence. Back nine: full emotional collapse.",
        "That hook was nasty, disrespectful, and kind of impressive.",
        "Course record dreams, muni-course decisions.",
        "One more double and this group chat becomes a crime scene.",
        "You don’t play this course. This course plays your ass.",
    ]
    return choice(lines)

