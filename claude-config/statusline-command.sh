#!/bin/sh
input=$(cat)

# --- Context window usage ---
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')

if [ -n "$used_pct" ]; then
  filled=$(echo "$used_pct" | awk '{printf "%d", ($1 / 100) * 10 + 0.5}')
  empty=$((10 - filled))
  bar=""
  i=0
  while [ "$i" -lt "$filled" ]; do
    bar="${bar}█"
    i=$((i + 1))
  done
  i=0
  while [ "$i" -lt "$empty" ]; do
    bar="${bar}░"
    i=$((i + 1))
  done
  ctx_pct=$(printf "%.0f%%" "$used_pct")
else
  bar="░░░░░░░░░░"
  ctx_pct="─"
fi

# --- Rate limit: 5-hour window ---
resets_at=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
rate_used=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')

if [ -n "$resets_at" ]; then
  reset_time=$(TZ="Asia/Taipei" date -r "$resets_at" "+%H:%M" 2>/dev/null)
  [ -z "$reset_time" ] && reset_time=$(TZ="Asia/Taipei" date -d "@${resets_at}" "+%H:%M" 2>/dev/null)
  [ -z "$reset_time" ] && reset_time="─"
else
  reset_time="─"
fi

if [ -n "$rate_used" ]; then
  remaining=$(echo "$rate_used" | awk '{printf "%.0f", 100 - $1}')
  rate_str="${remaining}%"
else
  rate_str="─"
fi

# --- Bar color based on usage (green → yellow → red) ---
if [ -n "$used_pct" ]; then
  bar_color=$(echo "$used_pct" | awk '{
    if ($1 < 50) print "\033[32m"
    else if ($1 < 75) print "\033[33m"
    else print "\033[31m"
  }')
else
  bar_color="\033[32m"
fi

# --- Output with colors ---
printf "%b🥐 [%s] %s\033[0m | \033[33m刷新: %s\033[0m | \033[32m額度: %s\033[0m" \
  "$bar_color" "$bar" "$ctx_pct" "$reset_time" "$rate_str"
