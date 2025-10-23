use owo_colors::OwoColorize;
use serde::Deserialize;
use std::fs::File;
use std::io::{self, BufRead, BufReader, Read};
use std::path::PathBuf;

const TOKEN_LIMIT: f64 = 200_000.0;

#[derive(Deserialize)]
struct Input {
    transcript_path: PathBuf,
    cwd: String,
    model: Model,
}

#[derive(Deserialize)]
struct Model {
    display_name: String,
}

#[derive(Deserialize)]
struct TranscriptEntry {
    message: Option<Message>,
}

#[derive(Deserialize)]
struct Message {
    usage: Option<Usage>,
}

#[derive(Deserialize)]
struct Usage {
    #[serde(default)]
    cache_creation_input_tokens: u64,
    #[serde(default)]
    cache_read_input_tokens: u64,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut stdin = io::stdin();
    let mut input_data = String::new();
    stdin.read_to_string(&mut input_data)?;

    let input: Input = serde_json::from_str(&input_data)?;

    let file = File::open(&input.transcript_path)?;
    let reader = BufReader::new(file);

    let mut current_token_usage = 0u64;

    for line in reader.lines() {
        let line = line?;
        if let Ok(entry) = serde_json::from_str::<TranscriptEntry>(&line) {
            if let Some(message) = entry.message {
                if let Some(usage) = message.usage {
                    let create_tokens = usage.cache_creation_input_tokens;
                    let read_tokens = usage.cache_read_input_tokens;
                    let input_tokens = create_tokens + read_tokens;

                    if input_tokens > 0 {
                        current_token_usage = input_tokens;
                    }
                }
            }
        }
    }

    let ratio = current_token_usage as f64 / TOKEN_LIMIT;
    let color = if ratio > 0.7 {
        "red"
    } else if ratio > 0.5 {
        "orange"
    } else if ratio > 0.3 {
        "yellow"
    } else {
        "grey69"
    };

    let percentage = (100.0 * current_token_usage as f64 / TOKEN_LIMIT) as i32;

    let percentage_str = format!("{}%", percentage);
    let colored_percentage = match color {
        "red" => percentage_str.red().to_string(),
        "orange" => percentage_str.truecolor(255, 165, 0).to_string(),
        "yellow" => percentage_str.yellow().to_string(),
        _ => percentage_str.truecolor(175, 175, 175).to_string(),
    };

    let path = PathBuf::from(&input.cwd);
    let colored_path = if let Some(filename) = path.file_name() {
        let parent = path.parent().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
        if !parent.is_empty() {
            format!(
                "{}/{}",
                parent.truecolor(175, 175, 175),
                filename.to_string_lossy().cyan()
            )
        } else {
            filename.to_string_lossy().cyan().to_string()
        }
    } else {
        input.cwd.truecolor(175, 175, 175).to_string()
    };

    println!(
        "{} {} {}",
        colored_path,
        colored_percentage,
        input.model.display_name.blue()
    );

    Ok(())
}
