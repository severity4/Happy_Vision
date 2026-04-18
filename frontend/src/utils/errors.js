/**
 * Map raw backend error strings into user-friendly Traditional Chinese.
 * Falls back to "處理失敗 · <raw>" when no pattern matches — the raw text
 * still gets shown so we don't lose debugging info, just demoted.
 */

const PATTERNS = [
  // Rate limiting
  { re: /429|rate.?limit|resource.?exhausted|too.?many.?requests/i,
    msg: '送出太快被 Gemini 限流了。請到設定把「每分鐘請求數 (RPM)」調低，或升級到付費方案' },

  // Timeouts
  { re: /timeout|timed.?out|deadline.?exceeded/i,
    msg: '網路連線不穩或 Gemini 回應太慢，會自動重試' },

  // Service errors
  { re: /500|502|503|504|unavailable|internal.?error/i,
    msg: 'Gemini 服務暫時不穩，已自動重試 3 次仍失敗，稍後可再試一次' },

  // Auth
  { re: /invalid.?api.?key|permission.?denied|unauthorized|401|403/i,
    msg: 'API Key 無效或已被撤銷。請到設定頁檢查' },

  // Exiftool
  { re: /exiftool.*not.?found|exiftool.*died/i,
    msg: 'exiftool 找不到或意外結束，請重新安裝 App' },
  { re: /exiftool.*timeout|metadata.?write.?failed/i,
    msg: '寫入照片標籤失敗（檔案可能被其他 App 鎖定）' },

  // File
  { re: /file.?not.?found|no.?such.?file/i,
    msg: '照片檔案找不到，可能被移走或刪除' },
  { re: /permission.?denied/i,
    msg: '沒有權限讀取照片，請檢查資料夾權限' },

  // Network
  { re: /connection.?refused|network.?error|dns.?resolution/i,
    msg: '連線 Gemini 失敗，請檢查網路' },

  // Parse
  { re: /json.?parse|invalid.?json|failed.?to.?parse/i,
    msg: 'Gemini 回傳格式異常，自動重試' },
]

export function humanizeError(raw) {
  if (!raw) return '處理失敗'
  const s = String(raw)
  for (const { re, msg } of PATTERNS) {
    if (re.test(s)) return msg
  }
  // Unknown — surface raw but prefix with something readable
  return `處理失敗 · ${s.slice(0, 120)}`
}
