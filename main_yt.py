import io
import requests
import pandas as pd
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import re
import os
from datetime import datetime, timedelta
# from google.colab import userdata
import logging
from urllib.parse import parse_qs, urlparse
import json
import gspread
import urllib.parse

def filter_df_by_date_range(df, start_date, end_date):
    """
    מסנן את הדאטהפריים לפי טווח תאריכים.

    פרמטרים:
    - df: DataFrame עם עמודת 'תאריך האירוע /השידור' בפורמט dd/mm/yyyy
    - start_date: מחרוזת בפורמט yyyy-mm-dd
    - end_date: מחרוזת בפורמט yyyy-mm-dd

    מחזיר:
    - DataFrame מסונן עם שורות בטווח התאריכים
    """
    df_copy = df.copy()
    df_copy['תאריך האירוע /השידור'] = pd.to_datetime(df_copy['תאריך האירוע /השידור'], format='mixed', dayfirst=True)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    filtered_df = df_copy[
        (df_copy['תאריך האירוע /השידור'] >= start_dt) &
        (df_copy['תאריך האירוע /השידור'] <= end_dt)
    ]

    return filtered_df


def extract_video_id(url):
    # אם מדובר בקישור מקוצר כמו youtu.be/ID
    if 'youtu.be' in url:
        return urlparse(url).path.strip('/')

    # אם מדובר בקישור רגיל עם פרמטר v
    parsed_url = urlparse(url)
    if parsed_url.hostname in ('www.youtube.com', 'youtube.com'):
        query = parse_qs(parsed_url.query)
        if 'v' in query:
            return query['v'][0]

    # אם מדובר בקישור embed
    match = re.search(r'/embed/([^/?]+)', url)
    if match:
        return match.group(1)

    # אם מדובר בקישור share עם timestamp
    match = re.search(r'/v/([^/?]+)', url)
    if match:
        return match.group(1)

    return None


def get_youtube_video_stats(video_id, API_KEY_YOUTUBE):
    # הוספנו את part=statistics לבקשה
    url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=contentDetails,statistics&id={video_id}&key={API_KEY_YOUTUBE}"
    )

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "items" in data and len(data) > 0:
            item = data["items"][0]
            # שליפת כמות הצפיות
            view_count = int(item["statistics"].get("viewCount", 0))

            return view_count

    except Exception as e:
        logging.error(f"Error fetching stats: {e}")
        return None


def update_youtube_views(df, API_KEY_YOUTUBE):
    """
    פונקציה שעוברת על ה-DataFrame, מחלצת מזהי סרטונים מיוטיוב,
    מושכת נתונים (כמו צפיות) דרך ה-API ומעדכנת את עמודת "כמות צפיות:".
    """
    for index, row in df.iterrows():
        link = row.get('לינק ליוטיוב')

        # מוודאים שהלינק קיים ושהוא לא מכיל רק 'X' או ריק
        if pd.notna(link) and link != 'X':

            # 1. חילוץ המזהה (ID) מהקישור
            video_id = extract_video_id(link)

            if video_id:
                # 2. קריאה לפונקציה שמביאה את הנתונים מיוטיוב
                stats = get_youtube_video_stats(video_id, API_KEY_YOUTUBE)

                # 3. אם חזרו נתונים, מעדכנים את ה-DataFrame
                if stats is not None:
                    df.at[index, "כמות צפיות:"] = str(stats)
                    logging.info(f"Updated row {index}: {stats} views for video {video_id}")
                else:
                    logging.info(f"Row {index}: Could not fetch stats for video {video_id}")
            else:
                sheet_row = index + 3
                logging.info(f"Row {sheet_row}: Could not extract video ID from link: {link}")
                # logging.info(f"Row {index}: Could not extract video ID from link: {link}")
        else:
            # דילוג על שורות ללא קישור תקין
            pass

    return df


# def get_authorized_gspread(SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE):
#     """פונקציית עזר ליצירת חיבור gspread עם התחזות"""
    
#     base_creds = service_account.Credentials.from_service_account_file(
#         SERVICE_ACCOUNT_FILE,
#         scopes=SCOPES
#     )
#     creds = base_creds.with_subject(USER_TO_IMPERSONATE)
#     return gspread.authorize(creds)



def get_all_values_with_links(worksheet):
    """
    שולף נתונים מגיליון גוגל ומחלץ קישורים מכל המיקומים האפשריים:
    היפר-קישור ישיר, Smart Chips ברמת התא, Smart Chips ברמת הטקסט, וערך גולמי.
    """
    spreadsheet = worksheet.spreadsheet
    encoded_title = urllib.parse.quote(worksheet.title)
    
    # מבקשים מה-API את כל השדות האפשריים שיכולים להכיל את הכתובת
    fields = "sheets(data(rowData(values(userEnteredValue,formattedValue,hyperlink,textFormatRuns,effectiveFormat/textFormat/link))))"
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet.id}?ranges={encoded_title}&fields={fields}"
    
    response = spreadsheet.client.request('get', url)
    data = response.json() if hasattr(response, 'json') else response
        
    sheets = data.get('sheets', [])
    if not sheets:
        return []
        
    row_data = sheets[0].get('data', [{}])[0].get('rowData', [])
    
    result = []
    for row in row_data:
        values = row.get('values', [])
        row_result = []
        for col in values:
            if not col:
                row_result.append('')
                continue
            
            found_link = None
            
            # 1. היפר-קישור ישיר (קישורים כחולים רגילים)
            if 'hyperlink' in col:
                found_link = col['hyperlink']
            
            # 2. Smart Chip שמוגדר על כל התא (המיקום הנפוץ ביותר לצ'יפים של יוטיוב)
            elif 'effectiveFormat' in col and 'textFormat' in col['effectiveFormat'] and 'link' in col['effectiveFormat']['textFormat'] and 'uri' in col['effectiveFormat']['textFormat']['link']:
                found_link = col['effectiveFormat']['textFormat']['link']['uri']
            
            # 3. Smart Chip שמוגדר כחלק מהטקסט או מילים בודדות לחיצות
            elif 'textFormatRuns' in col:
                for run in col['textFormatRuns']:
                    if 'format' in run and 'link' in run['format'] and 'uri' in run['format']['link']:
                        found_link = run['format']['link']['uri']
                        break
            
            # 4. לינק שהוזן כטקסט גולמי (ללא המרה לקישור כלל)
            elif 'userEnteredValue' in col and 'stringValue' in col['userEnteredValue']:
                original_input = col['userEnteredValue']['stringValue']
                if 'http' in original_input or 'youtu' in original_input:
                    found_link = original_input

            # הכנסת הלינק אם נמצא, אחרת הכנסת הטקסט המעוצב המוצג
            if found_link:
                row_result.append(found_link)
            else:
                row_result.append(col.get('formattedValue', ''))
                
        result.append(row_result)
        
    # השלמת תאים ריקים בשורות קצרות
    if result:
        max_len = max(len(r) for r in result)
        for r in result:
            r.extend([''] * (max_len - len(r)))
            
    return result


def get_authorized_gspread(service_account_info, scopes, user_to_impersonate):
    """חיבור gspread באמצעות מילון הרשאות והתחזות"""
    base_creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes
    )
    creds = base_creds.with_subject(user_to_impersonate)
    return gspread.authorize(creds)

def read_forcast_2027(SERVICE_ACCOUNT_INFO, SCOPES, USER_TO_IMPERSONATE, FILE_ID_FORCAST_2027):
    # 1. חיבור באמצעות התחזות וסקופ Sheets בלבד
    gc = get_authorized_gspread(SERVICE_ACCOUNT_INFO, SCOPES, USER_TO_IMPERSONATE)
    sh = gc.open_by_key(FILE_ID_FORCAST_2027)
    worksheet = sh.get_worksheet(0)

    # 2. שליפת הנתונים ישירות דרך Sheets API (ללא צורך ב-Drive API)
    all_values = worksheet.get_all_values()
    # all_values = get_all_values_with_links(worksheet)
    if not all_values or len(all_values) < 2:
        return pd.DataFrame()

    headers = [str(h).strip().replace('\n', ' ') for h in all_values[1]]
    data_rows = all_values[2:]
    
    df = pd.DataFrame(data_rows, columns=headers)

    columns_to_keep = [
        "תאריך האירוע /השידור",
        "שעת האירוע",
        "שעת סיום האירוע",
        "שם האירוע/פרוייקט",
        "תת קטגוריה",
        "שידור",
        "שמות המשתתפים באירוע",
        "סוג פעילות",
        'לינק ל-Youtube',
        "יום",
        # עמודות הנתונים המקוריות מהגיליון:
        "כמות צפיות:",
        "זמן צפיה ממוצע:"
    ]

    # שמירה על עמודות שקיימות בגיליון מתוך הרשימה
    existing_cols = [c for c in columns_to_keep if c in df.columns]
    df = df[existing_cols]

    if 'שידור' in df.columns:
        df['שידור'] = df['שידור'].astype(str).str.strip()
    if 'סוג פעילות' in df.columns:
        df['סוג פעילות'] = df['סוג פעילות'].astype(str).str.strip()

    df = df.rename(columns={
        'לינק ל-Youtube': 'לינק ליוטיוב'
    })

    # סינון הנתונים
    filtered_df = df[
        df['סוג פעילות'].isin(['סדרת רשת'])
    ].copy()

    if 'תאריך האירוע /השידור' in filtered_df.columns:
        filtered_df['תאריך האירוע /השידור'] = filtered_df['תאריך האירוע /השידור'].astype('object')
    if 'לינק ליוטיוב' in filtered_df.columns:
        filtered_df['לינק ליוטיוב'] = filtered_df['לינק ליוטיוב'].astype('object')

    return filtered_df


def update_forecast_in_google_sheets(forcast_df, FILE_ID_FORCAST_2027, SERVICE_ACCOUNT_INFO, SCOPES, USER_TO_IMPERSONATE):
    # 1. חיבור באמצעות התחזות
    gc = get_authorized_gspread(SERVICE_ACCOUNT_INFO, SCOPES, USER_TO_IMPERSONATE)
    sh = gc.open_by_key(FILE_ID_FORCAST_2027)
    worksheet = sh.get_worksheet(0)

    data = worksheet.get_all_values()
    # data = get_all_values_with_links(worksheet)
    if not data or len(data) < 2:
        logging.info("Error: No data in sheet.")
        return

    # שליפת הכותרות (שורה שנייה בקובץ, אינדקס 1)
    headers = [str(h).strip().replace('\n', ' ') for h in data[1]]

    # זיהוי עמודת מפתח בגוגל שיטס
    yt_col_idx = next((i for i, h in enumerate(headers) if 'לינק ל-Youtube' in h), None)

    if yt_col_idx is None:
        logging.info("Error: 'לינק ל-Youtube' column not found in the header row!")
        return

    # רשימת העמודות לעדכון בגוגל שיטס
    target_columns = [
        "כמות צפיות:"
    ]

    # מיפוי האינדקסים של העמודות לעדכון בגוגל שיטס
    col_indices = {col: headers.index(col) + 1 for col in target_columns if col in headers}
    updates_count = 0

    for _, row in forcast_df.iterrows():
        # בדיקה איך קוראים לעמודה ב-DataFrame (תומך בשני השמות)
        df_yt_col_name = 'לינק ל-Youtube' if 'לינק ל-Youtube' in row else 'לינק ליוטיוב'

        # שליפת הלינק מה-DataFrame
        yt_link_df = str(row.get(df_yt_col_name, '')).strip()

        # דילוג על שורות ללא לינק תקין
        if yt_link_df in ('', 'nan', 'None', 'X') or pd.isna(row.get(df_yt_col_name)):
            continue

        # חיפוש הלינק בשורות של הגוגל שיטס (מתחילים משורה 3)
        for r_idx, sheet_row in enumerate(data[2:], start=3):
            # מוודאים שהשורה מספיק ארוכה
            if len(sheet_row) > yt_col_idx:
                sheet_yt_link = str(sheet_row[yt_col_idx]).strip()
            else:
                sheet_yt_link = ""

            # השוואה בין הלינק מה-DataFrame ללינק בגוגל שיטס
            if sheet_yt_link == yt_link_df:
                logging.info(f"Match found on row {r_idx}! Link: {yt_link_df}")

                # עדכון העמודות הרלוונטיות
                for col_name in target_columns:
                    if col_name in row and col_name in col_indices and pd.notna(row[col_name]):
                        val = str(row[col_name])
                        c_idx = col_indices[col_name]
                        # עדכון התא הספציפי בגוגל שיטס
                        worksheet.update_cell(r_idx, c_idx, val)

                updates_count += 1
                break

    logging.info(f"Update complete! Updated {updates_count} rows in Google Sheets.")


def mainn():
    # FILE_ID_FORCAST_2027 = userdata.get('FILE_ID_FORCAST_2027')
    # API_KEY_YOUTUBE = userdata.get('API_KEY_YOUTUBE_NEW')
    FILE_ID_FORCAST_2027 = os.environ["FILE_ID_FORCAST_2027"]
    API_KEY_YOUTUBE = os.environ["API_KEY_YOUTUBE"]
    USER_TO_IMPERSONATE = os.environ["USER_TO_IMPERSONATE"]

    yesterday_date = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday_date.strftime('%Y-%m-%d')
    yesterday_str
    # START_DATE =  yesterday_str
    START_DATE =  "2026-01-01"
    END_DATE =  yesterday_str
    # END_DATE =  "2026-10-25"


    # הגדרת סקופ יחיד שמאושר באדמין
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    # SERVICE_ACCOUNT_FILE = 'creds-auto.json'
    # בראש הקובץ main_yt.py:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, 'creds-auto.json')
    # טעינת תוכן ה-JSON מתוך משתנה הסביבה והמרתו למילון
    service_account_info = json.loads(os.environ["CREDS_AUTO"])

    forcast_2027 = read_forcast_2027(service_account_info, SCOPES, USER_TO_IMPERSONATE, FILE_ID_FORCAST_2027)

    start_date =  START_DATE
    end_date =  END_DATE

    today_forcast = filter_df_by_date_range(forcast_2027, start_date, end_date)
    today_forcast = update_youtube_views(today_forcast, API_KEY_YOUTUBE)

    update_forecast_in_google_sheets(today_forcast, FILE_ID_FORCAST_2027, service_account_info, SCOPES, USER_TO_IMPERSONATE)