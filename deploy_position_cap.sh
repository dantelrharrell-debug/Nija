#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m "Add hard \$100 maximum position cap - safety improvement

- Add get_max_position_usd() to AdaptiveGrowthManager (\$100 hard limit)
- Update position sizing calculation to enforce hard cap: min(\$5) <= position <= max(\$100)
- Log position size with cap notation to show safety is enforced
- Prevents over-leveraging as account balance grows
- Ensures no single trade can exceed \$100 regardless of percentage calculation

This protects account from excessive single-position risk."

git push origin main
