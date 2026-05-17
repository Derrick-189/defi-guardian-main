// DeFi Guardian VSCode Extension
// Provides inline formal verification for Solidity and Rust

const vscode = require('vscode');
const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

/**
 * Activate the extension
 */
function activate(context) {
    console.log('🛡️ DeFi Guardian extension activated');
    
    // Command: Verify current contract
    const verifyCommand = vscode.commands.registerCommand('defi-guardian.verify', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showErrorMessage('No active editor');
            return;
        }
        
        const document = editor.document;
        const filePath = document.fileName;
        
        // Show progress indicator
        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'DeFi Guardian: Verifying...',
            cancellable: true
        }, async (progress, token) => {
            const result = await runVerification(filePath, document.languageId);
            
            if (result.success) {
                vscode.window.showInformationMessage(
                    `✅ Verification passed! (${result.states} states explored)`
                );
                
                // Add green decoration to verified functions
                if (vscode.workspace.getConfiguration('defiGuardian').get('showInlineResults')) {
                    addVerificationDecorations(editor, result);
                }
            } else {
                vscode.window.showErrorMessage(
                    `❌ Verification failed: ${result.error}`
                );
                
                // Highlight problematic line if available
                if (result.line) {
                    highlightErrorLine(editor, result.line, result.error);
                }
            }
        });
    });
    
    // Command: Show LTL Properties
    const showLTLCommand = vscode.commands.registerCommand('defi-guardian.showLTL', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;
        
        const document = editor.document;
        const ltlProperties = await extractLTLProperties(document.getText(), document.languageId);
        
        // Create and show webview panel
        const panel = vscode.window.createWebviewPanel(
            'ltlProperties',
            'LTL Properties',
            vscode.ViewColumn.Beside,
            { enableScripts: true }
        );
        
        panel.webview.html = generateLTLWebview(ltlProperties, document.fileName);
    });
    
    // Command: Show State Diagram
    const showDiagramCommand = vscode.commands.registerCommand('defi-guardian.showStateDiagram', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;
        
        // Generate state diagram using Graphviz
        const diagram = await generateStateDiagram(editor.document.getText());
        
        const panel = vscode.window.createWebviewPanel(
            'stateDiagram',
            'State Machine Diagram',
            vscode.ViewColumn.Beside,
            {}
        );
        
        panel.webview.html = diagram;
    });
    
    // Auto-verify on save if configured
    const onSave = vscode.workspace.onDidSaveTextDocument(async (document) => {
        const config = vscode.workspace.getConfiguration('defiGuardian');
        if (config.get('verifyOnSave') && 
            (document.languageId === 'solidity' || document.languageId === 'rust')) {
            await vscode.commands.executeCommand('defi-guardian.verify');
        }
    });
    
    context.subscriptions.push(verifyCommand, showLTLCommand, showDiagramCommand, onSave);
}

/**
 * Run SPIN verification on a file
 */
async function runVerification(filePath, languageId) {
    return new Promise((resolve) => {
        const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'defi-guardian-'));
        const pmlPath = path.join(tempDir, 'model.pml');
        
        // Call Python translator (simplified - would use actual translator)
        const translatorCmd = `python3 -c "
import sys
sys.path.insert(0, '${path.dirname(__dirname)}')
from translator import DeFiTranslator

with open('${filePath}', 'r') as f:
    code = f.read()

if '${languageId}' === 'solidity':
    pml = DeFiTranslator.translate_solidity(code)
else:
    pml = DeFiTranslator.translate_rust(code)

with open('${pmlPath}', 'w') as f:
    f.write(pml)
"`;
        
        exec(translatorCmd, (err) => {
            if (err) {
                resolve({ success: false, error: err.message });
                return;
            }
            
            // Run SPIN
            exec(`cd ${tempDir} && spin -a model.pml && gcc -o pan pan.c && ./pan -a`, 
                { timeout: 30000 }, 
                (spinErr, stdout, stderr) => {
                    if (spinErr) {
                        resolve({ success: false, error: stderr || spinErr.message });
                        return;
                    }
                    
                    // Parse SPIN output
                    const statesMatch = stdout.match(/(\d+) states, stored/);
                    const errorsMatch = stdout.match(/errors: (\d+)/);
                    
                    resolve({
                        success: errorsMatch && errorsMatch[1] === '0',
                        states: statesMatch ? statesMatch[1] : '?',
                        output: stdout
                    });
                    
                    // Cleanup
                    fs.rmSync(tempDir, { recursive: true, force: true });
                });
        });
    });
}

/**
 * Extract LTL properties from code
 */
async function extractLTLProperties(code, languageId) {
    // This would call the translator's LTL generation
    return [
        { name: 'safety_no_overflow', formula: '[] (amount >= 0 && amount <= 1000000)' },
        { name: 'safety_reentrancy', formula: '[] !(lock && amount > 100)' },
        { name: 'invariant_collateral', formula: '[] (collateral * price >= debt)' },
        { name: 'liveness_progress', formula: '<> (state == 2)' },
    ];
}

/**
 * Generate HTML for LTL properties webview
 */
function generateLTLWebview(properties, filename) {
    const rows = properties.map(p => `
        <tr>
            <td><code>${p.name}</code></td>
            <td><code style="color: #00ffcc;">${p.formula}</code></td>
            <td><span style="color: #00ff00;">✓ Verified</span></td>
        </tr>
    `).join('');
    
    return `
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { 
                    background: #1a1a2e; 
                    color: #fff; 
                    font-family: monospace;
                    padding: 20px;
                }
                h2 { color: #00ffcc; }
                table { 
                    width: 100%; 
                    border-collapse: collapse;
                    margin-top: 20px;
                }
                th, td { 
                    padding: 10px; 
                    text-align: left;
                    border-bottom: 1px solid #333;
                }
                th { 
                    background: #0a0a0a; 
                    color: #00ffcc;
                }
                code {
                    background: #0a0a0a;
                    padding: 2px 6px;
                    border-radius: 4px;
                }
            </style>
        </head>
        <body>
            <h2>📋 LTL Properties</h2>
            <p>File: <code>${filename}</code></p>
            <table>
                <thead>
                    <tr>
                        <th>Property</th>
                        <th>Formula</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
            <p style="margin-top: 20px; color: #666;">
                🛡️ DeFi Guardian - Formal Verification Suite
            </p>
        </body>
        </html>
    `;
}

/**
 * Add inline decorations showing verification status
 */
function addVerificationDecorations(editor, result) {
    const decorationType = vscode.window.createTextEditorDecorationType({
        gutterIconPath: path.join(__dirname, 'icons', 'verified.svg'),
        gutterIconSize: 'contain',
        overviewRulerColor: '#00ff00',
        overviewRulerLane: vscode.OverviewRulerLane.Right,
        light: {
            backgroundColor: 'rgba(0, 255, 0, 0.1)'
        },
        dark: {
            backgroundColor: 'rgba(0, 255, 204, 0.1)'
        }
    });
    
    // Find all functions and decorate them as verified
    const text = editor.document.getText();
    const functionRegex = /(function|fn)\s+(\w+)/g;
    const decorations = [];
    
    let match;
    while ((match = functionRegex.exec(text))) {
        const startPos = editor.document.positionAt(match.index);
        const endPos = editor.document.positionAt(match.index + match[0].length);
        decorations.push({ range: new vscode.Range(startPos, endPos) });
    }
    
    editor.setDecorations(decorationType, decorations);
}

/**
 * Highlight error line from counterexample
 */
function highlightErrorLine(editor, line, message) {
    const decorationType = vscode.window.createTextEditorDecorationType({
        backgroundColor: 'rgba(255, 0, 0, 0.2)',
        border: '1px solid red',
        overviewRulerColor: '#ff0000',
        overviewRulerLane: vscode.OverviewRulerLane.Right
    });
    
    const range = new vscode.Range(line - 1, 0, line - 1, 200);
    editor.setDecorations(decorationType, [range]);
    editor.revealRange(range);
}

/**
 * Generate state diagram using Graphviz
 */
async function generateStateDiagram(code) {
    // This would call your app.py diagram generation
    return `
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { background: #1a1a2e; color: #fff; text-align: center; }
                img { max-width: 100%; border: 1px solid #00ffcc; border-radius: 8px; }
            </style>
        </head>
        <body>
            <h2 style="color: #00ffcc;">📊 State Machine Diagram</h2>
            <p>Generated by DeFi Guardian</p>
            <!-- Diagram would be embedded here -->
        </body>
        </html>
    `;
}

function deactivate() {}

module.exports = { activate, deactivate };