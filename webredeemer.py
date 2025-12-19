from time import sleep

from DrissionPage import Chromium, ChromiumOptions


def redeemer_in_web(polymarket_url="https://polymarket.com/portfolio?tab=positions"):
    # 选择赎回
    try:
        co1 = (ChromiumOptions()
               .set_browser_path(rf'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
               .set_local_port(9331)
               .set_user_data_path(rf'C:\Users\Initial\AppData\Local\Temp\DrissionPage\userData\9331\Default'))

        # 创建多个页面对象
        tab1 = Chromium(addr_or_opts=co1).latest_tab
        tab1.get(url=polymarket_url)
        try:
            tab1.ele('@text()=Claim',timeout=5).click()
            sleep(0.1)
        except Exception as e:
            print(f"未找到可赎回项...")

        try:
            tab1.ele('@text()=Claim proceeds', timeout=5).click()
            sleep(0.1)

            try:
                tab1.ele('@text()=Done', timeout=30).click()
                sleep(0.1)
            except Exception as e:
                print(f"赎回超过30秒...")

        except Exception as e:
            print(f"Try Again...")
            tab1.ele('@text()=Try Again', timeout=5).click()
            sleep(0.1)

    except Exception as e:
        print(f"页面选择赎回失败...")

if __name__ == '__main__':
    redeemer_in_web("https://polymarket.com/portfolio?tab=positions")

