// Lê o texto de cada .jpg de uma pasta com o Vision da Apple (macOS).
// Uso: ocr_vision <pasta> <saida.json>
// Saída: {"arquivo.jpg": [{"t": texto, "c": confiança, "x", "y", "w", "h"}]}, caixa normalizada com origem embaixo à esquerda.
import AppKit
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write("uso: ocr_vision <pasta> <saida.json>\n".data(using: .utf8)!)
    exit(1)
}
let pasta = URL(fileURLWithPath: args[1])
let nomes = try FileManager.default.contentsOfDirectory(atPath: pasta.path).filter { $0.hasSuffix(".jpg") }.sorted()
var resultado: [String: [[String: Any]]] = [:]

for nome in nomes {
    guard let img = NSImage(contentsOf: pasta.appendingPathComponent(nome)),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let pedido = VNRecognizeTextRequest()
    pedido.recognitionLevel = .accurate
    pedido.recognitionLanguages = ["pt-BR", "en-US", "es-ES"]
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([pedido])
    var itens: [[String: Any]] = []
    for obs in pedido.results ?? [] {
        guard let melhor = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        itens.append(["t": melhor.string, "c": Double(melhor.confidence),
                      "x": Double(b.minX), "y": Double(b.minY), "w": Double(b.width), "h": Double(b.height)])
    }
    resultado[nome] = itens
}

let dados = try JSONSerialization.data(withJSONObject: resultado, options: [])
try dados.write(to: URL(fileURLWithPath: args[2]))
