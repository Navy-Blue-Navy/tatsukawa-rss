import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://www.sanyo.or.jp/news/"
OUTPUT = Path(__file__).parent / "tatsukawa.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(
    r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
)

MAX_RETRIES = 3


# --------------------------------------------------
# HTTP取得
# --------------------------------------------------

def fetch(url, label):

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(
                f"{label} "
                f"{attempt}/{MAX_RETRIES}"
            )

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP:",
                response.status_code
            )

            response.raise_for_status()

            return response

        except requests.RequestException as e:

            print(
                "取得失敗:",
                e
            )

            if attempt < MAX_RETRIES:

                print(
                    "10秒待って再試行します。"
                )

                time.sleep(10)

    return None


# --------------------------------------------------
# 既存RSS読み込み
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:

        tree = ET.parse(OUTPUT)

        for item in tree.getroot().findall(
            "./channel/item"
        ):

            guid = item.findtext(
                "guid",
                ""
            )

            if not guid:
                continue

            old_items[guid] = {
                "title": item.findtext(
                    "title",
                    ""
                ),
                "link": item.findtext(
                    "link",
                    ""
                ),
                "description": item.findtext(
                    "description",
                    ""
                ),
                "pubDate": item.findtext(
                    "pubDate",
                    ""
                ),
                "guid": guid,
            }

    except Exception as e:

        print(
            "既存RSS読み込みエラー:",
            e
        )

        print(
            "安全のため今回は更新しません。"
        )

        raise SystemExit(0)


print(
    "既存RSS件数:",
    len(old_items)
)


# --------------------------------------------------
# 全ページ取得
# --------------------------------------------------

page_urls = [
    "https://www.sanyo.or.jp/news/",
    "https://www.sanyo.or.jp/news/index_2.html",
    "https://www.sanyo.or.jp/news/index_3.html",
]

current_items = []
failed = False


for page_number, page_url in enumerate(
    page_urls,
    start=1
):

    print()
    print("=" * 70)
    print(
        f"{page_number}ページ目"
    )
    print("=" * 70)

    response = fetch(
        page_url,
        "ページ取得"
    )


    if response is None:

        print(
            f"{page_number}ページ目を"
            "取得できませんでした。"
        )

        failed = True
        break


    soup = BeautifulSoup(
        response.content,
        "html.parser"
    )


    blocks = soup.select(
        "dl.news_list"
    )


    print(
        "記事候補:",
        len(blocks),
        "件"
    )


    # 現在は1ページ20件程度あるため、
    # 0件なら構造変更等の可能性が高い
    if len(blocks) == 0:

        print(
            "記事が0件です。"
        )

        print(
            "ページ構造変更の可能性があります。"
        )

        failed = True
        break


    page_count = 0


    for block in blocks:

        # ------------------------------------------
        # 日付
        # ------------------------------------------

        day_element = block.select_one(
            "span.day"
        )

        if day_element is None:
            continue


        date_text = day_element.get_text(
            " ",
            strip=True
        )


        match = DATE_RE.search(
            date_text
        )

        if not match:
            continue


        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))


        # ------------------------------------------
        # 記事リンク・タイトル
        # ------------------------------------------

        a = block.find(
            "a",
            href=True
        )

        if a is None:
            continue


        link = urljoin(
            page_url,
            a["href"]
        )


        # 個別記事だけ対象
        if "/news/details/" not in link:
            continue


        title = a.get_text(
            " ",
            strip=True
        )


        title = re.sub(
            r"\s+",
            " ",
            title
        ).strip()


        if not title:
            continue


        # ------------------------------------------
        # カテゴリ
        # ------------------------------------------

        category = ""

        dt = block.find(
            "dt"
        )

        if dt is not None:

            dt_text = dt.get_text(
                " ",
                strip=True
            )

            dt_text = re.sub(
                r"\s+",
                " ",
                dt_text
            ).strip()

            # 日付部分を除いて残った文字列をカテゴリとする
            category = dt_text.replace(
                date_text,
                ""
            ).strip()


        # ------------------------------------------
        # RSS日付
        # ------------------------------------------

        pub_dt = datetime(
            year,
            month,
            day,
            12,
            0,
            0,
            tzinfo=JST
        )


        # ------------------------------------------
        # GUID
        # ------------------------------------------

        guid = hashlib.sha256(
            (
                "tatsukawa|"
                + link
            ).encode("utf-8")
        ).hexdigest()


        # ------------------------------------------
        # description
        # ------------------------------------------

        if category:

            description = (
                "カテゴリ："
                + category
            )

        else:

            description = (
                "辰川会のお知らせ"
            )


        current_items.append({
            "title": title,
            "link": link,
            "description": description,
            "pubDate": format_datetime(
                pub_dt
            ),
            "guid": guid,
        })


        page_count += 1


    print(
        "有効記事:",
        page_count,
        "件"
    )


# --------------------------------------------------
# 途中失敗時は更新しない
# --------------------------------------------------

if failed:

    print()
    print(
        "全ページを正常取得できなかったため、"
    )

    print(
        "既存XMLをそのまま維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 重複除去
# --------------------------------------------------

unique_current = []
seen = set()


for item in current_items:

    if item["guid"] in seen:
        continue

    seen.add(
        item["guid"]
    )

    unique_current.append(
        item
    )


current_items = unique_current


print()
print("=" * 70)
print(
    "全ページ合計:",
    len(current_items),
    "件"
)
print("=" * 70)


if len(current_items) == 0:

    print(
        "有効記事を1件も取得できませんでした。"
    )

    print(
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 既存RSSと統合
# --------------------------------------------------

all_items = []
seen_guids = set()


# 現在サイト上にある記事
for item in current_items:

    if item["guid"] in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        item["guid"]
    )


# 将来ページから押し出された記事もRSSには残す
for guid, item in old_items.items():

    if guid in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        guid
    )


# --------------------------------------------------
# 日付順
# --------------------------------------------------

def get_date(item):

    try:

        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS生成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)


ET.SubElement(
    channel,
    "title"
).text = (
    "辰川会のお知らせ"
)


ET.SubElement(
    channel,
    "link"
).text = SOURCE_URL


ET.SubElement(
    channel,
    "description"
).text = (
    "社会医療法人社団 沼南会・"
    "社会福祉法人 さんようの"
    "辰川会グループ お知らせ"
)


ET.SubElement(
    channel,
    "language"
).text = "ja"


# --------------------------------------------------
# RSS記事
# --------------------------------------------------

for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )


    ET.SubElement(
        element,
        "title"
    ).text = item["title"]


    ET.SubElement(
        element,
        "link"
    ).text = item["link"]


    ET.SubElement(
        element,
        "description"
    ).text = item["description"]


    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]


    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# XML保存
# --------------------------------------------------

tree = ET.ElementTree(
    rss
)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


# --------------------------------------------------
# 結果
# --------------------------------------------------

print()
print("RSS作成成功")

print(
    "現在サイトから取得:",
    len(current_items),
    "件"
)

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)


print()
print("最新20件:")


for i, item in enumerate(
    all_items[:20],
    start=1
):

    print()

    print(
        f"[{i}] "
        f"{item['pubDate']} "
        f"{item['title']}"
    )

    print(
        "    ",
        item["description"]
    )

    print(
        "    ",
        item["link"]
    )