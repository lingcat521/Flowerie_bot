#!/usr/bin/env php
<?php
// 最小「任意语言插件」示例：PHP 实现 Plugin API v1（stdin/stdout JSON-Lines）
$in = fopen('php://stdin', 'r');
while (($line = fgets($in)) !== false) {
    if (!preg_match('/"id":\s*([0-9]+)/', $line, $m)) {
        continue;
    }
    $id = $m[1];
    $method = preg_match('/"method":\s*"([a-z_]+)"/', $line, $mm) ? $mm[1] : '';
    switch ($method) {
        case 'initialize':
            echo '{"id":' . $id . ',"result":{"ok":true,"api_version":"1"}}', PHP_EOL;
            break;
        case 'event':
            echo '{"id":' . $id . ',"result":{"actions":[{"type":"test","message":"php-ok"}]}}', PHP_EOL;
            break;
        case 'health':
        case 'shutdown':
            echo '{"id":' . $id . ',"result":{"ok":true}}', PHP_EOL;
            break;
        default:
            echo '{"id":' . $id . ',"error":"unknown method"}', PHP_EOL;
    }
    fflush(STDOUT);
}

