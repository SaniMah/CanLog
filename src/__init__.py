"""CAN Log Analyser source package.

Planned modules (added in their build steps):
    db.py        database engine + schema helpers   (Step 2)
    load.py      read a CAN log into the database    (Step 1/2)
    profile.py   learn "normal" per CAN ID           (Step 1/3)
    detect.py    anomaly rules -> anomaly table       (Step 4)
    evaluate.py  precision/recall vs labels           (Step 5)
    report.py    LLM test report from numbers         (Step 7)
"""
