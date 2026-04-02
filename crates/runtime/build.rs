use std::env;
use std::fs;
use std::path::Path;

fn main() {
    let out_dir = env::var("OUT_DIR").unwrap();
    let out_path = Path::new(&out_dir);
    let assets_dir = Path::new("assets/skills");

    println!("cargo:rerun-if-changed=assets/skills");

    let mut skill_names: Vec<String> = Vec::new();

    if assets_dir.exists() {
        let mut dirs: Vec<_> = fs::read_dir(assets_dir)
            .expect("read assets/skills")
            .filter_map(Result::ok)
            .filter(|e| e.file_type().map_or(false, |t| t.is_dir()))
            .collect();
        dirs.sort_by_key(|e| e.file_name());

        let skills_out = out_path.join("skills");
        fs::create_dir_all(&skills_out).expect("create skills out dir");

        for entry in dirs {
            let skill_md = entry.path().join("SKILL.md");
            if skill_md.exists() {
                let name = entry.file_name().to_string_lossy().to_string();
                // Copy skill file to OUT_DIR so include_str! can reference it
                let dest = skills_out.join(format!("{name}.md"));
                fs::copy(&skill_md, &dest).expect("copy skill file");
                skill_names.push(name);
            }
        }
    }

    // Generate Rust source referencing the copied files via include_str!
    let mut code = String::from(
        "/// Bundled ARIS skills compiled into the binary.\n\
         pub static BUNDLED_SKILLS: &[(&str, &str)] = &[\n",
    );
    for name in &skill_names {
        code.push_str(&format!(
            "    (\"{name}\", include_str!(concat!(env!(\"OUT_DIR\"), \"/skills/{name}.md\"))),\n"
        ));
    }
    code.push_str("];\n");

    fs::write(out_path.join("bundled_skills.rs"), code).expect("write bundled_skills.rs");

    println!("cargo:warning=Embedded {} bundled skills", skill_names.len());
}
