<?php
/**
 * API pour lancer / suivre le scraping depuis le viewer (WAMP).
 */

declare(strict_types=1);

header('X-Content-Type-Options: nosniff');

$viewerDir = __DIR__;
$projectDir = dirname($viewerDir);
$statusFile = $projectDir . DIRECTORY_SEPARATOR . 'scraper_status.json';
$lockFile = $projectDir . DIRECTORY_SEPARATOR . 'scraper.lock';
$logFile = $projectDir . DIRECTORY_SEPARATOR . 'scraper_run.log';
$envBat = $projectDir . DIRECTORY_SEPARATOR . 'pdf_env.bat';
$runner = $projectDir . DIRECTORY_SEPARATOR . 'launch_scrape_task.bat';

$action = $_GET['action'] ?? 'status';

function read_status(string $path): array
{
    if (!is_file($path)) {
        return ['state' => 'idle'];
    }
    $raw = file_get_contents($path);
    if ($raw === false || trim($raw) === '') {
        return ['state' => 'idle'];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : ['state' => 'idle'];
}

function json_response(array $payload, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

function log_tail_has_error(string $logFile): ?string
{
    if (!is_file($logFile)) {
        return null;
    }
    $content = (string) file_get_contents($logFile);
    $pos = strrpos($content, '====');
    $tail = $pos === false ? $content : substr($content, $pos);
    if (str_contains($tail, 'ModuleNotFoundError')) {
        return 'Playwright introuvable — pip install playwright && playwright install chromium';
    }
    if (preg_match('/SystemExit:\s*(.+)/', $tail, $m)) {
        return trim($m[1]);
    }
    if (str_contains($tail, 'Traceback (most recent call last)')) {
        if (preg_match('/\n([A-Za-z_][\w.]*(?:Error|Exit)[^\r\n]*)\s*$/', $tail, $m)) {
            return trim($m[1]);
        }
        return 'Erreur Python (voir scraper_run.log)';
    }
    return null;
}

function enrich_status(array $status, string $statusFile, string $lockFile, string $logFile): array
{
    $updatedAt = $status['updatedAt'] ?? null;
    $ageSec = 0;
    if (is_string($updatedAt)) {
        $ts = strtotime($updatedAt);
        if ($ts !== false) {
            $ageSec = time() - $ts;
        }
    }

    $state = $status['state'] ?? 'idle';
    if (in_array($state, ['waiting_manual', 'manual_ready', 'scraping'], true)) {
        if ($ageSec > 20 && !is_file($lockFile)) {
            $logError = log_tail_has_error($logFile);
            if ($logError !== null) {
                $status['state'] = 'error';
                $status['message'] = $logError;
                @file_put_contents($statusFile, json_encode($status, JSON_UNESCAPED_UNICODE));
            }
        }
    }

    if ($state === 'starting' && $ageSec > 25 && !is_file($lockFile)) {
        $logError = log_tail_has_error($logFile);
        $status['state'] = 'error';
        $status['message'] = $logError ?? 'Le navigateur de scraping n\'a pas démarré.';
        @file_put_contents($statusFile, json_encode($status, JSON_UNESCAPED_UNICODE));
    }

    return $status;
}

function launch_scraper(string $projectDir, string $logFile, string $runner): bool
{
    if (!is_file($runner)) {
        return false;
    }
    $stamp = gmdate('Y-m-d H:i:s') . ' UTC';
    @file_put_contents($logFile, "==== {$stamp} PHP lance scrape ====\n", FILE_APPEND);

    $taskCfg = $projectDir . DIRECTORY_SEPARATOR . 'scraper_task.json';
    if (is_file($taskCfg)) {
        $cfg = json_decode((string) file_get_contents($taskCfg), true);
        $taskName = is_array($cfg) ? ($cfg['taskName'] ?? '') : '';
        if ($taskName !== '') {
            $runCmd = 'schtasks /Run /TN ' . escapeshellarg($taskName) . ' 2>&1';
            exec($runCmd, $out, $code);
            @file_put_contents(
                $logFile,
                'schtasks /Run ' . $taskName . ' code=' . $code . ' ' . implode(' ', $out) . "\n",
                FILE_APPEND
            );
            if ($code === 0) {
                return true;
            }
        }
    }

    // Secours : fenêtre visible (peut rester invisible si Apache = service système).
    if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
        $cmd = 'cmd /C start "Skoda Scraper" /D '
            . escapeshellarg($projectDir) . ' '
            . escapeshellarg($runner);
        pclose(popen($cmd, 'r'));
        return true;
    }

    $cmd = 'cd ' . escapeshellarg($projectDir) . ' && '
        . escapeshellarg($runner) . ' > /dev/null 2>&1 &';
    pclose(popen($cmd, 'r'));
    return true;
}

function reset_scraper(string $projectDir, string $statusFile, string $lockFile): void
{
    $python = $projectDir . DIRECTORY_SEPARATOR . 'pdf_python_path.txt';
    $py = 'python';
    if (is_file($python)) {
        $line = trim((string) file_get_contents($python));
        if ($line !== '') {
            $py = $line;
        }
    }
    $stopScript = $projectDir . DIRECTORY_SEPARATOR . 'stop_scraper.py';
    if (is_file($stopScript)) {
        @exec(escapeshellarg($py) . ' ' . escapeshellarg($stopScript) . ' 2>NUL');
    }
    if (is_file($lockFile)) {
        @unlink($lockFile);
    }
    @file_put_contents($statusFile, json_encode([
        'state' => 'idle',
        'message' => 'Réinitialisé.',
        'updatedAt' => gmdate('c'),
    ], JSON_UNESCAPED_UNICODE));
}

switch ($action) {
    case 'start':
        if (!is_file($envBat)) {
            json_response([
                'ok' => false,
                'error' => 'Configuration Python absente. Lancez : python setup_local_env.py',
            ], 500);
        }

        if (is_file($lockFile)) {
            $age = time() - (int) @filemtime($lockFile);
            if ($age < 7200) {
                $status = enrich_status(read_status($statusFile), $statusFile, $lockFile, $logFile);
                $st = $status['state'] ?? 'idle';
                if (in_array($st, ['waiting_manual', 'manual_ready', 'scraping', 'starting'], true)) {
                    json_response(['ok' => true, 'alreadyRunning' => true, 'status' => $status]);
                }
            }
            @unlink($lockFile);
        }

        @file_put_contents($statusFile, json_encode([
            'state' => 'starting',
            'message' => 'Ouverture du navigateur Chromium…',
            'updatedAt' => gmdate('c'),
        ], JSON_UNESCAPED_UNICODE));

        if (!launch_scraper($projectDir, $logFile, $runner)) {
            json_response(['ok' => false, 'error' => 'launch_scrape_task.bat introuvable.'], 500);
        }

        json_response(['ok' => true, 'started' => true]);

    case 'reset':
        reset_scraper($projectDir, $statusFile, $lockFile);
        json_response(['ok' => true, 'status' => read_status($statusFile)]);

    case 'status':
        $status = enrich_status(read_status($statusFile), $statusFile, $lockFile, $logFile);
        json_response(['ok' => true, 'status' => $status]);

    default:
        json_response(['ok' => false, 'error' => 'Action inconnue.'], 400);
}
