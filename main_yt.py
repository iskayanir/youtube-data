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

import gspread

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

# def read_forcast_2027():

#   # 1. טעינת ההרשאות מה-Service Account והפקת Access Token
#   creds = service_account.Credentials.from_service_account_file(
#       'creds-auto.json',
#       scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
#   )
#   creds.refresh(Request())

#   # 2. קישור הורדה ישיר דרך Drive API
#   url = f"https://docs.google.com/spreadsheets/d/{FILE_ID_FORCAST_2027}/export?format=csv"
#   headers = {'Authorization': f'Bearer {creds.token}'}

#   response = requests.get(url, headers=headers)
#   response.raise_for_status()

#   # הגדרת העמודות שברצונך לטעון (כולל העמודות החדשות לשמירה)
#   columns_to_keep = [
#       "תאריך האירוע /השידור",
#       "שעת האירוע",
#       "שעת סיום האירוע",
#       "שם האירוע/פרוייקט",
#       "תת קטגוריה",
#       "שידור",
#       "שמות המשתתפים באירוע",
#       "סוג פעילות",
#       'לינק ל-Youtube',
#       "יום",
#       # עמודות הנתונים המקוריות מהגיליון:
#       "כמות צפיות:",
#       "זמן צפיה ממוצע:"

#   ]

#   # 3. קריאה ב-Pandas עם סינון עמודות מראש (usecols)
#   df = pd.read_csv(io.StringIO(response.text), header=1, usecols=columns_to_keep)

#   # הסרת שורה 0 הראשונה (משורה 1 ב-DataFrame והלאה)
#   df = df.iloc[1:].reset_index(drop=True)

#   df['שידור'] = df['שידור'].astype(str).str.strip()
#   df['סוג פעילות'] = df['סוג פעילות'].astype(str).str.strip()

#   df = df.rename(columns={
#       'לינק ל-Youtube': 'לינק ליוטיוב'
#   })

#   # סינון הנתונים
#   filtered_df = df[
#       df['סוג פעילות'].isin(['סדרת רשת'])
#   ].copy()

#   filtered_df['תאריך האירוע /השידור'] = filtered_df['תאריך האירוע /השידור'].astype('object')
#   filtered_df['לינק ליוטיוב'] = filtered_df['לינק ליוטיוב'].astype('object')

#   return filtered_df

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
                logging.info(f"Row {index}: Could not extract video ID from link: {link}")
        else:
            # דילוג על שורות ללא קישור תקין
            pass

    return df


# def update_forecast_in_google_sheets(forcast_df):
#     gc = gspread.service_account(filename='creds-auto.json')
#     sh = gc.open_by_key(FILE_ID_FORCAST_2027)
#     worksheet = sh.get_worksheet(0)

#     data = worksheet.get_all_values()
#     # שליפת הכותרות (מניח שהן בשורה השנייה בקובץ, אינדקס 1)
#     headers = [str(h).strip().replace('\n', ' ') for h in data[1]]

#     # זיהוי עמודת מפתח בגוגל שיטס - השם המדויק
#     yt_col_idx = next((i for i, h in enumerate(headers) if 'לינק ל-Youtube' in h), None)

#     if yt_col_idx is None:
#         print("Error: 'לינק ל-Youtube' column not found in the header row!")
#         return

#     # רשימת העמודות שאנחנו רוצים לעדכן בגוגל שיטס
#     target_columns = [
#         "כמות צפיות:"
#     ]

#     # מיפוי האינדקסים של העמודות לעדכון בגוגל שיטס
#     col_indices = {col: headers.index(col) + 1 for col in target_columns if col in headers}
#     updates_count = 0

#     for _, row in forcast_df.iterrows():
#         # בדיקה איך קוראים לעמודה ב-DataFrame (תומך בשני השמות)
#         df_yt_col_name = 'לינק ל-Youtube' if 'לינק ל-Youtube' in row else 'לינק ליוטיוב'

#         # שליפת הלינק מה-DataFrame
#         yt_link_df = str(row.get(df_yt_col_name, '')).strip()

#         # דילוג על שורות ללא לינק תקין
#         if yt_link_df in ('', 'nan', 'None', 'X') or pd.isna(row.get(df_yt_col_name)):
#             continue

#         # חיפוש הלינק בשורות של הגוגל שיטס (מתחילים משורה 3)
#         for r_idx, sheet_row in enumerate(data[2:], start=3):
#             # מוודאים שהשורה מספיק ארוכה
#             if len(sheet_row) > yt_col_idx:
#                 sheet_yt_link = str(sheet_row[yt_col_idx]).strip()
#             else:
#                 sheet_yt_link = ""

#             # השוואה בין הלינק מה-DataFrame ללינק בגוגל שיטס
#             if sheet_yt_link == yt_link_df:
#                 print(f"Match found on row {r_idx}! Link: {yt_link_df}")

#                 # עדכון העמודות הרלוונטיות
#                 for col_name in target_columns:
#                     if col_name in row and col_name in col_indices and pd.notna(row[col_name]):
#                         val = str(row[col_name])
#                         c_idx = col_indices[col_name]
#                         # עדכון התא הספציפי בגוגל שיטס
#                         worksheet.update_cell(r_idx, c_idx, val)

#                 updates_count += 1
#                 break

#     print(f"Update complete! Updated {updates_count} rows in Google Sheets.")


def get_authorized_gspread(SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE):
    """פונקציית עזר ליצירת חיבור gspread עם התחזות"""
    
    base_creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )
    creds = base_creds.with_subject(USER_TO_IMPERSONATE)
    return gspread.authorize(creds)


def read_forcast_2027(SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE, FILE_ID_FORCAST_2027):
    # 1. חיבור באמצעות התחזות וסקופ Sheets בלבד
    gc = get_authorized_gspread(SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE)
    sh = gc.open_by_key(FILE_ID_FORCAST_2027)
    worksheet = sh.get_worksheet(0)

    # 2. שליפת הנתונים ישירות דרך Sheets API (ללא צורך ב-Drive API)
    all_values = worksheet.get_all_values()
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


def update_forecast_in_google_sheets(forcast_df, FILE_ID_FORCAST_2027, SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE):
    # 1. חיבור באמצעות התחזות
    gc = get_authorized_gspread(SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE)
    sh = gc.open_by_key(FILE_ID_FORCAST_2027)
    worksheet = sh.get_worksheet(0)

    data = worksheet.get_all_values()
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
    START_DATE =  yesterday_str
    # START_DATE =  "2026-10-25"
    END_DATE =  yesterday_str
    # END_DATE =  "2026-10-25"


    # הגדרת סקופ יחיד שמאושר באדמין
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    # SERVICE_ACCOUNT_FILE = 'creds-auto.json'
    # בראש הקובץ main_yt.py:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, 'creds-auto.json')
    forcast_2027 = read_forcast_2027(SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE, FILE_ID_FORCAST_2027)

    start_date =  START_DATE
    end_date =  END_DATE

    today_forcast = filter_df_by_date_range(forcast_2027, start_date, end_date)
    today_forcast = update_youtube_views(today_forcast, API_KEY_YOUTUBE)

    update_forecast_in_google_sheets(today_forcast, FILE_ID_FORCAST_2027, SERVICE_ACCOUNT_FILE, SCOPES, USER_TO_IMPERSONATE)