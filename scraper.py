import asyncio
from playwright.async_api import async_playwright
import json
from datetime import datetime, timedelta
import random

# TSHP 課程查詢網址
TARGET_URL = "https://www.tshp.org.tw/ehc-tshp/s/w/edu/teachMst/teachMstB2"

async def scrape_tshp():
    data_list = []
    
    print("啟動瀏覽器模擬...")
    async with async_playwright() as p:
        # 啟動 Chromium 瀏覽器 (headless=True 代表不顯示視窗，適合伺服器執行)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            print(f"前往網站: {TARGET_URL}")
            await page.goto(TARGET_URL, timeout=60000)
            
            # --- 步驟：設定查詢範圍 ---
            # 設定從「今天」到「未來 180 天」，確保資料庫包含所有可能查詢的課程
            today = datetime.now()
            future = today + timedelta(days=180)
            
            # 轉換為民國年格式 (例如 113/01/01)
            def to_roc_date(dt):
                return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"

            str_start = to_roc_date(today)
            str_end = to_roc_date(future)
            
            print(f"輸入查詢區間: {str_start} ~ {str_end}")

            # 尋找日期輸入框 (根據網頁結構通常是 input type=text)
            # 這裡假設網頁有兩個日期輸入框，分別為開始與結束
            date_inputs = page.locator("input.date") # 嘗試用 class 定位，若失敗會fallback
            if await date_inputs.count() < 2:
                # 備用方案：抓所有 text input
                date_inputs = page.locator("input[type='text']")
            
            if await date_inputs.count() >= 2:
                await date_inputs.nth(0).fill(str_start)
                await date_inputs.nth(1).fill(str_end)
            else:
                print("⚠️ 警告：找不到日期輸入框，將直接查詢預設範圍")

            # --- 步驟：勾選 '開放報名' ---
            # 嘗試點擊含有「開放報名」文字的 label 或其旁邊的 checkbox
            try:
                # 先找 label
                target_label = page.locator("label", has_text="開放報名")
                if await target_label.count() > 0:
                    await target_label.click()
                    print("已勾選 '開放報名'")
                else:
                    print("找不到 '開放報名' 選項，略過此步驟")
            except Exception as e:
                print(f"勾選失敗: {e}")

            # --- 步驟：點擊查詢 ---
            print("點擊查詢按鈕...")
            # 尋找按鈕
            search_btn = page.locator("button, input[type='button'], a").filter(has_text="查詢")
            if await search_btn.count() > 0:
                await search_btn.first.click()
            else:
                await page.keyboard.press("Enter")
            
            # 等待表格載入
            await page.wait_for_timeout(3000)
            
            # --- 步驟：抓取列表 ---
            rows = await page.locator("table tr").all()
            print(f"找到 {len(rows)} 列資料")

            for i, row in enumerate(rows):
                # 跳過標頭 (通常第一列是標題)
                text_content = await row.inner_text()
                if "積分" in text_content and "課程" in text_content and i < 2:
                    continue

                cols = await row.locator("td").all()
                if len(cols) < 5: continue
                
                # 欄位解析 (依照您的需求)
                # [0] 課程期間
                # [1] 積分用途
                # [2] 課程主題 (含連結)
                # [3] 申請單位
                # [4] 積分
                
                period = await cols[0].inner_text()
                topic_el = cols[2].locator("a")
                topic = await cols[2].inner_text()
                points = await cols[4].inner_text()
                
                # 取得連結
                link = "#"
                if await topic_el.count() > 0:
                    link = await topic_el.get_attribute("href")
                    if link and not link.startswith("http"):
                        link = "https://www.tshp.org.tw" + link

                print(f"  > 發現課程: {topic.strip()[:20]}...")

                # --- 步驟：進入內頁抓取報名狀態 ---
                reg_status = "未標明"
                if link != "#":
                    try:
                        # 開啟新分頁以保留原列表
                        new_page = await context.new_page()
                        await new_page.goto(link, timeout=15000)
                        
                        # 抓取頁面文字判斷狀態
                        page_text = await new_page.locator("body").inner_text()
                        
                        if "開放報名" in page_text:
                            reg_status = "開放報名"
                        elif "報名額滿" in page_text or "額滿" in page_text:
                            reg_status = "報名額滿"
                        elif "報名截止" in page_text:
                            reg_status = "報名截止"
                        elif "尚未開放" in page_text:
                            reg_status = "尚未開放"
                        else:
                            reg_status = "請查看詳情"
                            
                        await new_page.close()
                    except Exception as e:
                        print(f"    內頁讀取錯誤: {e}")
                        reg_status = "讀取失敗"
                        if not new_page.is_closed(): await new_page.close()
                
                # 存入列表
                data_list.append({
                    "period": period.strip(),
                    "topic": topic.strip(),
                    "points": points.strip(),
                    "reg_status": reg_status,
                    "link": link
                })
                
                # 隨機延遲，避免被網站封鎖
                await asyncio.sleep(random.uniform(0.5, 1.5))

        except Exception as main_e:
            print(f"執行過程發生錯誤: {main_e}")
        finally:
            await browser.close()

    # 存檔
    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S (GMT+8)"),
        "data": data_list
    }
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print("✅ 資料已儲存至 data.json")

if __name__ == "__main__":
    asyncio.run(scrape_tshp())