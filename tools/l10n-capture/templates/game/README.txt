將模板 PNG 放在此目錄：

- loading_arrow_right.png  （右方向鍵，無文字）
- continue_btn_cap.png     （繼續按鈕左側金邊，勿含文字）
- buy_bonus_btn.png        （Buy Bonus 按鈕圖示區，勿含各語系文字）

產生方式：

  npm.cmd run prepare-templates -- "右箭頭.png" "繼續按鈕整顆.png" "BuyBonus按鈕整顆.png"

第三個參數可選：從 Buy Bonus 按鈕裁切左側圖示區（無文字），產生 buy_bonus_btn.png。

若無 buy_bonus_btn.png，擷取時會略過 Buy 彈窗（buyBonus.optional=true）。
