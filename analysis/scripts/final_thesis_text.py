"""
Crude text search in ~/paper_context/thesis.pdf (no poppler or pypdf on this host): inflate every
Flate stream and print the text around a search term from TJ / Tj operators. Read-only.
Usage: python3 analysis/scripts/final_thesis_text.py [term ...]   (default: "omposite")
"""

import os
import re
import sys
import zlib

PDF = os.path.expanduser("~/paper_context/thesis.pdf")


def text(s):
    res = []
    for arr, single, op in re.findall(rb"\[(.*?)\]\s*TJ|\((.*?)(?<!\\)\)\s*Tj|(T\*|Td|TD|ET)", s, re.S):
        if arr:
            for p, k in re.findall(rb"\((.*?)(?<!\\)\)|(-?\d+\.?\d*)", arr):
                if p:
                    res.append(p.decode("latin1"))
                elif k and float(k) < -200:
                    res.append(" ")
        elif single:
            res.append(single.decode("latin1"))
        elif op:
            res.append("\n" if op in (b"T*", b"ET") else " ")
    return "".join(res)


def main():
    terms = sys.argv[1:] or ["omposite"]
    data = open(PDF, "rb").read()
    for i, m in enumerate(re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)):
        try:
            t = text(zlib.decompress(m.group(1)))
        except zlib.error:
            continue
        for term in terms:
            for h in re.finditer(term, t):
                print(f"[stream {i}] ..." + t[max(0, h.start() - 300):h.start() + 400].replace("\n", " ") + "...\n")


if __name__ == "__main__":
    main()
