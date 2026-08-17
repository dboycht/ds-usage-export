# 获取 userToken 的三种方式

工具需要「内部登录后」的登录态 —— 即你在浏览器里登录 platform.deepseek.com 后产生的
`userToken`（浏览器 localStorage）。任选一种方式获取。

---

## 方式一：控制台复制（推荐，最通用）

1. 用 Chrome / Edge / Firefox 登录 <https://platform.deepseek.com>，并打开用量页
   <https://platform.deepseek.com/usage>。
2. 按 `F12` 打开开发者工具，切换到 **Console（控制台）** 标签。
3. 粘贴下面这行并回车（会把 Token 复制到剪贴板，不会显示在屏幕上）：

```js
copy(JSON.parse(localStorage.getItem('userToken')).value)
```

4. 将剪贴板内容粘贴到工具：
   - CLI：`dsu login`（交互式，不回显），或 `dsu login --token <token>`
   - Web：打开 `dsu serve` 页面，粘贴到输入框并点「保存并验证」

> 提示：若执行后报错，说明登录态键名有变化，可先执行 `Object.keys(localStorage)` 查看。

## 方式二：书签小工具（一键复制）

1. 在浏览器收藏夹新建书签，网址填：

```
javascript:(function(){try{var t=JSON.parse(localStorage.getItem('userToken')).value;navigator.clipboard.writeText(t);alert('userToken 已复制到剪贴板');}catch(e){alert('未登录或键名变化: '+e.message);}})();
```

2. 在 platform.deepseek.com 用量页点击该书签，即可复制 Token。

## 方式三：浏览器扩展（可选，自动化）

如果你已安装 Playwright，可运行附带脚本自动从 Chrome 配置读取：

```bash
pip install playwright && playwright install chromium
python -m dsusage.browser_token
```

> 该方式需要关闭 Chrome 或使用独立配置目录，读取的是本地浏览器配置文件，
> 属于「可选增强」，v1.0.1 以方式一为主。

---

## 安全提醒

- `userToken` 等同账号登录凭证，**泄露即账号泄露**（可查看/操作你的用量与 API Key）。
- 本工具仅在**本机**保存（`~/.dsusage/config.json`），Web 界面默认只绑定 `127.0.0.1`。
- 不要截图、分享、提交到代码仓库；退出使用可执行 `dsu logout` 清除。
- 导出文件（尤其含 API Key 名称的汇总）同样注意保密。
