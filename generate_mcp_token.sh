#!/bin/bash

# MCP Bearer Token Generator
# Usage: ./generate_mcp_token.sh <subject> <scopes> <expiration>
# Example: ./generate_mcp_token.sh "user@example.com" "admin,read" "4H"

# Check if correct number of arguments provided
if [ $# -ne 3 ]; then
    echo "Usage: $0 <subject> <scopes> <expiration>"
    echo "Example: $0 'user@example.com' 'admin,read,write' '4H'"
    echo "Example: $0 'user@company.com' 'admin' '1d'"
    echo ""
    echo "Expiration format: 1H, 4H, 1d, 7d, etc. (H=hours, d=days)"
    exit 1
fi

# Parameters
SUBJECT="$1"
SCOPES_INPUT="$2"
EXPIRATION="$3"

# Fixed values
ISSUER="https://observeinc.com"
AUDIENCE="observe-community"
PRIVATE_KEY="_secure/private_key.pem"

# Check if private key exists
if [ ! -f "$PRIVATE_KEY" ]; then
    echo "Error: $PRIVATE_KEY not found in current directory"
    exit 1
fi

# Convert comma-separated scopes to JSON array
IFS=',' read -ra SCOPE_ARRAY <<< "$SCOPES_INPUT"
SCOPES_JSON="["
for i in "${!SCOPE_ARRAY[@]}"; do
    if [ $i -gt 0 ]; then
        SCOPES_JSON+=","
    fi
    SCOPES_JSON+="\"${SCOPE_ARRAY[i]}\""
done
SCOPES_JSON+="]"

# Get current timestamp
NOW=$(date +%s)

# Calculate expiration timestamp based on input
case ${EXPIRATION: -1} in
    H|h)
        HOURS=${EXPIRATION%?}
        EXP=$(date -v+${HOURS}H +%s)
        ;;
    d|D)
        DAYS=${EXPIRATION%?}
        EXP=$(date -v+${DAYS}d +%s)
        ;;
    *)
        echo "Error: Invalid expiration format. Use format like '4H' or '1d'"
        exit 1
        ;;
esac

# Generate the MCP Bearer token
echo "Generating MCP Bearer token..."
echo "Subject: $SUBJECT"
echo "Scopes: $SCOPES_JSON"
echo "Expires: $(date -r $EXP)"
echo ""

TOKEN=$(jwt encode \
  --alg RS256 \
  --secret @"$PRIVATE_KEY" \
  "{\"iss\":\"$ISSUER\",\"sub\":\"$SUBJECT\",\"aud\":\"$AUDIENCE\",\"scopes\":$SCOPES_JSON,\"exp\":$EXP,\"iat\":$NOW}")

echo "Generated Token:"
echo "$TOKEN"

# Optional: Copy to clipboard (uncomment if you want this feature)
# echo "$TOKEN" | pbcopy
# echo ""
# echo "Token copied to clipboard!"