#!/usr/bin/env perl
# 最小「任意语言插件」示例：Perl 实现 Plugin API v1（stdin/stdout JSON-Lines）
use strict;
use warnings;
$| = 1;    # 关闭输出缓冲（协议要求逐行即时响应）

while (my $line = <STDIN>) {
    my ($id)     = $line =~ /"id":\s*(\d+)/;
    my ($method) = $line =~ /"method":\s*"([a-z_]+)"/;
    next unless defined $id && defined $method;

    if    ($method eq 'initialize') { print qq({"id":$id,"result":{"ok":true,"api_version":"1"}}\n); }
    elsif ($method eq 'event')      { print qq({"id":$id,"result":{"actions":[{"type":"test","message":"perl-ok"}]}}\n); }
    elsif ($method eq 'health')     { print qq({"id":$id,"result":{"ok":true}}\n); }
    elsif ($method eq 'shutdown')   { print qq({"id":$id,"result":{"ok":true}}\n); }
    else                            { print qq({"id":$id,"error":"unknown method"}\n); }
}

