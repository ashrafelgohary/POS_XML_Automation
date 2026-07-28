#!/bin/bash
set -e

echo "🔍 Verifying setup before production build..."
echo ""

# Check Dockerfiles
echo "1️⃣ Checking ansible/Dockerfile..."
if grep -q "WORKDIR /app/ansible" ansible/Dockerfile && \
   grep -q "runner_api:app" ansible/Dockerfile; then
    echo "   ✅ ansible/Dockerfile OK"
else
    echo "   ❌ ansible/Dockerfile MISSING WORKDIR or CMD"
    exit 1
fi

echo ""
echo "2️⃣ Checking gui_upload/Dockerfile..."
if grep -q "WORKDIR /app/gui_upload" gui_upload/Dockerfile && \
   grep -q "app:app" gui_upload/Dockerfile; then
    echo "   ✅ gui_upload/Dockerfile OK"
else
    echo "   ❌ gui_upload/Dockerfile MISSING WORKDIR or CMD"
    exit 1
fi

echo ""
echo "3️⃣ Checking docker-compose.yml..."
TOKEN_COUNT=$(grep -c "RUNNER_API_TOKEN" docker-compose.yml || echo 0)
if [ "$TOKEN_COUNT" -ge 2 ]; then
    echo "   ✅ RUNNER_API_TOKEN in both services"
else
    echo "   ❌ RUNNER_API_TOKEN not in both services"
    exit 1
fi

if grep -q "healthcheck:" ansible/Dockerfile || \
   grep -q "HEALTHCHECK" ansible/Dockerfile; then
    echo "   ✅ HEALTHCHECK defined"
fi

echo ""
echo "4️⃣ Checking for override files..."
OVERRIDES=$(ls docker-compose.*-*.yml 2>/dev/null | wc -l)
if [ "$OVERRIDES" -gt 0 ]; then
    echo "   ⚠️  Found override files:"
    ls docker-compose.*-*.yml
    echo "   👉 Move to archive/ before production build"
else
    echo "   ✅ No override files present"
fi

echo ""
echo "5️⃣ Checking requirements.txt files..."
if [ -f "ansible/requirements.txt" ]; then
    echo "   ✅ ansible/requirements.txt exists"
    cat ansible/requirements.txt
else
    echo "   ❌ ansible/requirements.txt missing"
    exit 1
fi

echo ""
if [ -f "gui_upload/requirements.txt" ]; then
    echo "   ✅ gui_upload/requirements.txt exists"
    cat gui_upload/requirements.txt
else
    echo "   ❌ gui_upload/requirements.txt missing"
    exit 1
fi

echo ""
echo "6️⃣ Testing config..."
sudo docker compose config --quiet && echo "   ✅ docker-compose.yml valid"

echo ""
echo "✅ ALL CHECKS PASSED - Ready for production build!"
